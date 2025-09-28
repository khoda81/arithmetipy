from arithmetipy import ArithmeticDecoder, ArithmeticEncoder

ALPHABET_SIZE = 3
SEQUENCE = [0, 1, 2, 1, 1, 0, 1, 2]
ENCODED = b"3\xd4"


def test_encode():
    # --- Encode ---
    encoder = ArithmeticEncoder()
    for symbol in SEQUENCE:
        # here: (start, end, denominator)
        encoder.encode(symbol, symbol + 1, ALPHABET_SIZE)

    encoded = encoder.read()
    assert encoded == ENCODED


def test_decode():
    decoder = ArithmeticDecoder(ENCODED)
    # All symbols have uniform weight
    weights = [1] * ALPHABET_SIZE
    out = [decoder.decode_next(weights) for _ in SEQUENCE]

    assert out == SEQUENCE


def test_encode_decode():
    encoder = ArithmeticEncoder()
    for symbol in SEQUENCE:
        encoder.encode(symbol, symbol + 1, ALPHABET_SIZE)
    encoded = encoder.read()

    decoder = ArithmeticDecoder(encoded)
    weights = [1] * ALPHABET_SIZE
    out = [decoder.decode_next(weights) for _ in SEQUENCE]

    assert out == SEQUENCE
