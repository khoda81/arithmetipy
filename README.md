# Arithmetipy

Python bindings for a Rust implementation of **arithmetic coding**.  
This library provides streaming **arithmetic encoder** and **decoder** with 32-bit precision.  
It’s built in Rust for speed, exposed to Python via [PyO3](https://github.com/PyO3/pyo3) and [maturin]

---

## Installation

```bash
pip install arithmetipy
```

## Develop

```bash
pip install maturin
git clone https://github.com/yourname/arithmetipy
cd arithmetipy
maturin develop
````

## Usage

```python
from arithmetipy import ArithmeticEncoder, ArithmeticDecoder

# Our "alphabet" is integers {0, 1, 2}
alphabet_size = 3
seq = [0, 1, 2, 1, 1, 0, 1, 2]

# --- Encode ---
encoder = ArithmeticEncoder()
for symbol in seq:
    # here: (start, end, denominator)
    encoder.encode(symbol, symbol + 1, alphabet_size)

encoded = encoder.read()
print("Encoded bytes:", encoded)

# --- Decode ---
decoder = ArithmeticDecoder(encoded)
# All symbols have uniform weight
weights = [1] * alphabet_size
out = [decoder.decode_next(weights) for _ in seq]
print("Decoded symbols:", out)

assert out == seq
```

Output:

```
Encoded bytes: b'3\xd4'
Decoded symbols: [0, 1, 2, 1, 1, 0, 1, 2]
```

---

## API

### `ArithmeticEncoder`

* `encode(start: int, end: int, denominator: int) -> None`
  Encode a symbol interval.
* `read() -> bytes`
  Get the encoded byte stream and reset the internal buffer.

### `ArithmeticDecoder`

* `__init__(data: bytes)`
  Create a decoder from an encoded byte stream.
* `decode_next(weights: List[int]) -> int`
  Decode the next symbol given its weights (probability distribution).

