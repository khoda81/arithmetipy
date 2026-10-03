#!/usr/bin/env python3
"""
Depth-aware Nobitex FX router.

Examples:
  # Spend 10,000,000 toman and find the best executable synthetic USDT route:
  python scripts/nobitex_fx_router.py 10000000 --from TOMAN --to USDT

  # Sell 1,000 USDT for toman:
  python scripts/nobitex_fx_router.py 1000 --from USDT --to TOMAN

  # Use exact account fee tier without putting the token on the command line:
  NOBITEX_TOKEN=... python scripts/nobitex_fx_router.py 10000000 --from TOMAN --to USDT

  # Override fees explicitly (percent, not fraction):
  python scripts/nobitex_fx_router.py 10000000 --from TOMAN --to USDT \
      --fee-irt-pct 0.25 --fee-usdt-pct 0.13

By default the direct USDTIRT market is excluded from routing because during the
night restriction its book may still update while matching is unavailable.
Pass --include-direct when you know it is executable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from typing import Iterable

getcontext().prec = 40

API = "https://apiv2.nobitex.ir"
DEFAULT_BRIDGES = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "TRX", "LTC")

# Fallbacks are the example values currently shown in Nobitex's API docs for a
# user profile. They are NOT guaranteed to be your account tier.
DOC_EXAMPLE_FEE_IRT_PCT = Decimal("0.35")
DOC_EXAMPLE_FEE_USDT_PCT = Decimal("0.20")


@dataclass(frozen=True)
class Market:
    symbol: str
    base: str
    quote: str


@dataclass
class Leg:
    market: Market
    src: str
    dst: str
    amount_in: Decimal
    gross_out: Decimal
    net_out: Decimal
    fee_pct: Decimal
    vwap: Decimal
    worst_price: Decimal
    levels: int


@dataclass
class Route:
    currencies: tuple[str, ...]
    legs: list[Leg]
    amount_in: Decimal
    amount_out: Decimal


def D(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def fetch_json(path: str, token: str | None = None) -> dict:
    headers = {
        "Accept": "application/json",
        "User-Agent": "nobitex-synthetic-fx-router/1.0",
    }
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def fee_rates(args: argparse.Namespace) -> tuple[Decimal, Decimal, str]:
    explicit_irt = D(args.fee_irt_pct) if args.fee_irt_pct is not None else None
    explicit_usdt = D(args.fee_usdt_pct) if args.fee_usdt_pct is not None else None

    token = os.environ.get("NOBITEX_TOKEN")
    profile_rates: tuple[Decimal, Decimal] | None = None
    if token and (explicit_irt is None or explicit_usdt is None):
        profile = fetch_json("/users/profile", token)
        if profile.get("status") == "ok":
            opts = profile["profile"]["options"]
            profile_rates = (D(opts["fee"]), D(opts["feeUsdt"]))

    irt = explicit_irt
    usdt = explicit_usdt
    source_parts: list[str] = []
    if explicit_irt is not None or explicit_usdt is not None:
        source_parts.append("CLI override")

    if profile_rates is not None:
        if irt is None:
            irt = profile_rates[0]
        if usdt is None:
            usdt = profile_rates[1]
        source_parts.append("authenticated Nobitex profile")

    if irt is None:
        irt = DOC_EXAMPLE_FEE_IRT_PCT
    if usdt is None:
        usdt = DOC_EXAMPLE_FEE_USDT_PCT

    if not source_parts:
        source = "API-doc example fallback (set NOBITEX_TOKEN or fee flags for your exact tier)"
    else:
        source = " + ".join(source_parts)
        if profile_rates is None and (
            explicit_irt is None or explicit_usdt is None
        ):
            source += " + API-doc fallback for unspecified fee"

    return irt, usdt, source


def normalize_currency(name: str) -> tuple[str, Decimal]:
    name = name.upper()
    if name == "TOMAN":
        # Nobitex IRT order-book prices are returned in rial-valued API units.
        return "IRT", Decimal("10")
    if name in {"IRR", "RLS"}:
        return "IRT", Decimal("1")
    return name, Decimal("1")


def market_fee_pct(market: Market, fee_irt_pct: Decimal, fee_usdt_pct: Decimal) -> Decimal:
    if market.quote == "IRT":
        return fee_irt_pct
    if market.quote == "USDT":
        return fee_usdt_pct
    raise ValueError(f"No fee rule for quote currency {market.quote}")


def top(book: dict) -> tuple[Decimal, Decimal, float]:
    bid = D(book["bids"][0][0])
    ask = D(book["asks"][0][0])
    last_update = int(book.get("lastUpdate") or 0)
    age = (time.time() * 1000 - last_update) / 1000 if last_update else float("nan")
    return bid, ask, age


def execute_leg(
    amount_in: Decimal,
    src: str,
    dst: str,
    market: Market,
    book: dict,
    fee_pct: Decimal,
) -> Leg | None:
    fee_frac = fee_pct / Decimal("100")

    if src == market.base and dst == market.quote:
        # Sell base -> quote against bids.
        remaining = amount_in
        gross = Decimal("0")
        base_filled = Decimal("0")
        worst = Decimal("0")
        levels = 0
        for price_s, qty_s in book.get("bids", []):
            price, qty = D(price_s), D(qty_s)
            if price <= 0 or qty <= 0:
                continue
            take = min(remaining, qty)
            if take <= 0:
                continue
            gross += take * price
            base_filled += take
            remaining -= take
            worst = price
            levels += 1
            if remaining <= 0:
                break
        if remaining > 0 or base_filled <= 0:
            return None
        vwap = gross / base_filled

    elif src == market.quote and dst == market.base:
        # Buy base with quote against asks.
        remaining = amount_in
        gross = Decimal("0")
        quote_spent = Decimal("0")
        worst = Decimal("0")
        levels = 0
        for price_s, qty_s in book.get("asks", []):
            price, qty = D(price_s), D(qty_s)
            if price <= 0 or qty <= 0:
                continue
            level_quote = price * qty
            spend = min(remaining, level_quote)
            if spend <= 0:
                continue
            gross += spend / price
            quote_spent += spend
            remaining -= spend
            worst = price
            levels += 1
            if remaining <= 0:
                break
        if remaining > 0 or gross <= 0:
            return None
        vwap = quote_spent / gross

    else:
        raise ValueError(f"{src}->{dst} is not an edge of {market.symbol}")

    # Nobitex reports fees in the asset received by the trade in its examples;
    # applying the percentage to each leg's output also composes naturally.
    net = gross * (Decimal("1") - fee_frac)
    return Leg(
        market=market,
        src=src,
        dst=dst,
        amount_in=amount_in,
        gross_out=gross,
        net_out=net,
        fee_pct=fee_pct,
        vwap=vwap,
        worst_price=worst,
        levels=levels,
    )


def route_markets(bridges: Iterable[str], include_direct: bool) -> list[Market]:
    markets: list[Market] = []
    for asset in bridges:
        markets.append(Market(f"{asset}IRT", asset, "IRT"))
        markets.append(Market(f"{asset}USDT", asset, "USDT"))
    if include_direct:
        markets.append(Market("USDTIRT", "USDT", "IRT"))
    return markets


def adjacency(markets: Iterable[Market]) -> dict[str, list[tuple[str, Market]]]:
    graph: dict[str, list[tuple[str, Market]]] = {}
    for m in markets:
        graph.setdefault(m.base, []).append((m.quote, m))
        graph.setdefault(m.quote, []).append((m.base, m))
    return graph


def enumerate_paths(
    graph: dict[str, list[tuple[str, Market]]],
    src: str,
    dst: str,
    max_hops: int,
) -> list[list[tuple[str, Market]]]:
    out: list[list[tuple[str, Market]]] = []

    def dfs(cur: str, seen: set[str], edges: list[tuple[str, Market]]) -> None:
        if len(edges) > max_hops:
            return
        if cur == dst:
            out.append(edges.copy())
            return
        if len(edges) == max_hops:
            return
        for nxt, market in graph.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            edges.append((nxt, market))
            dfs(nxt, seen, edges)
            edges.pop()
            seen.remove(nxt)

    dfs(src, {src}, [])
    return out


def simulate_route(
    amount: Decimal,
    src: str,
    path: list[tuple[str, Market]],
    books: dict,
    fee_irt_pct: Decimal,
    fee_usdt_pct: Decimal,
) -> Route | None:
    cur = src
    value = amount
    legs: list[Leg] = []
    currencies = [src]
    for nxt, market in path:
        book = books.get(market.symbol)
        if not book:
            return None
        fee = market_fee_pct(market, fee_irt_pct, fee_usdt_pct)
        leg = execute_leg(value, cur, nxt, market, book, fee)
        if leg is None:
            return None
        legs.append(leg)
        value = leg.net_out
        cur = nxt
        currencies.append(cur)
    return Route(tuple(currencies), legs, amount, value)


def fmt(x: Decimal, places: int = 6) -> str:
    q = Decimal(1).scaleb(-places)
    try:
        return f"{x.quantize(q):,f}"
    except InvalidOperation:
        return f"{x:,f}"


def print_books(markets: list[Market], books: dict) -> None:
    print("Top of book")
    print("market        bid                 ask            spread(bp)   age(s)")
    for m in markets:
        book = books.get(m.symbol)
        if not book or not book.get("bids") or not book.get("asks"):
            continue
        bid, ask, age = top(book)
        spread = (ask / bid - Decimal("1")) * Decimal("10000")
        print(
            f"{m.symbol:10}  {float(bid):16,.8g}  {float(ask):16,.8g}"
            f"  {float(spread):10.2f}  {age:7.2f}"
        )
    print()


def path_name(route: Route, display_src: str, display_dst: str) -> str:
    currencies = list(route.currencies)
    if display_src == "TOMAN":
        currencies[0] = "TOMAN"
    if display_dst == "TOMAN":
        currencies[-1] = "TOMAN"
    return " -> ".join(currencies)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Compare depth-aware, fee-corrected synthetic conversion paths on Nobitex."
    )
    p.add_argument("amount", type=Decimal, help="Amount in --from currency")
    p.add_argument("--from", dest="src", default="TOMAN", help="Source currency (default: TOMAN)")
    p.add_argument("--to", dest="dst", default="USDT", help="Destination currency (default: USDT)")
    p.add_argument(
        "--bridges",
        default=",".join(DEFAULT_BRIDGES),
        help="Comma-separated bridge assets",
    )
    p.add_argument("--max-hops", type=int, default=2)
    p.add_argument(
        "--include-direct",
        action="store_true",
        help="Allow direct USDTIRT routing (use only when matching is open)",
    )
    p.add_argument("--fee-irt-pct", type=Decimal, default=None)
    p.add_argument("--fee-usdt-pct", type=Decimal, default=None)
    p.add_argument("--top", type=int, default=8, help="Number of routes to print")
    p.add_argument(
        "--no-books",
        action="store_true",
        help="Do not print top-of-book snapshot",
    )
    args = p.parse_args()

    display_src = args.src.upper()
    display_dst = args.dst.upper()
    src, src_scale = normalize_currency(display_src)
    dst, dst_scale = normalize_currency(display_dst)

    if args.amount <= 0:
        p.error("amount must be positive")

    amount_internal = args.amount * src_scale

    fee_irt_pct, fee_usdt_pct, fee_source = fee_rates(args)
    bridges = tuple(x.strip().upper() for x in args.bridges.split(",") if x.strip())
    markets = route_markets(bridges, args.include_direct)

    data = fetch_json("/v3/orderbook/all")
    if data.get("status") != "ok":
        raise RuntimeError(f"Nobitex returned status={data.get('status')!r}")

    if not args.no_books:
        print_books(markets, data)

    print(
        f"Fees: IRT-quoted={fee_irt_pct}%  USDT-quoted={fee_usdt_pct}%"
        f"  [{fee_source}]"
    )
    print(
        f"Input: {fmt(args.amount, 8)} {display_src}"
        + (
            f" = {fmt(amount_internal, 0)} Nobitex IRT API units"
            if display_src == "TOMAN"
            else ""
        )
    )
    print()

    graph = adjacency(markets)
    paths = enumerate_paths(graph, src, dst, args.max_hops)
    routes: list[Route] = []
    for path in paths:
        result = simulate_route(
            amount_internal,
            src,
            path,
            data,
            fee_irt_pct,
            fee_usdt_pct,
        )
        if result is not None:
            routes.append(result)

    if not routes:
        print("No route had enough displayed depth to execute the full amount.", file=sys.stderr)
        return 2

    routes.sort(key=lambda r: r.amount_out, reverse=True)
    best = routes[0]

    def display_out(value: Decimal) -> Decimal:
        return value / dst_scale

    print("Executable routes (including full displayed-depth slippage + fees)")
    for i, route in enumerate(routes[: args.top], 1):
        out = display_out(route.amount_out)
        if {src, dst} == {"IRT", "USDT"}:
            if src == "IRT":
                # Internal IRT units are rial-valued; divide by 10 for toman/USDT.
                toman_per_usdt = (route.amount_in / route.amount_out) / Decimal("10")
            else:
                toman_per_usdt = (route.amount_out / route.amount_in) / Decimal("10")
            rate = f"{float(toman_per_usdt):,.2f} toman/USDT"
        else:
            rate = f"{float(out / args.amount):,.10g} {display_dst}/{display_src}"

        leg_desc = "; ".join(
            f"{leg.market.symbol} vwap={float(leg.vwap):,.8g} "
            f"fee={leg.fee_pct}% levels={leg.levels}"
            for leg in route.legs
        )
        marker = "  <-- BEST" if i == 1 else ""
        print(
            f"{i:2}. {path_name(route, display_src, display_dst):24}"
            f" out={fmt(out, 8):>18} {display_dst:5}"
            f"  effective={rate}{marker}"
        )
        print(f"    {leg_desc}")

    if len(routes) > 1:
        second = routes[1]
        advantage_bp = (
            best.amount_out / second.amount_out - Decimal("1")
        ) * Decimal("10000")
        print()
        print(f"Best-vs-second advantage: {float(advantage_bp):.2f} bp")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
