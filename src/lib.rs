use arithmetify::arith32::Interval;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use arithmetify::{
    ArithmeticDecoder as ArithmeticDecoder32, ArithmeticEncoder as ArithmeticEncoder32,
};

/// An arithmetic encoder for compressing sequences of symbols.
///
/// This class encodes symbols incrementally given their probability
/// intervals, and produces a compressed byte stream that can later be
/// decoded by [`ArithmeticDecoder`].
#[pyclass]
pub struct ArithmeticEncoder {
    inner: ArithmeticEncoder32,
}

#[pymethods]
impl ArithmeticEncoder {
    /// Create a new arithmetic encoder.
    #[new]
    fn new() -> Self {
        Self {
            inner: ArithmeticEncoder32::new(),
        }
    }

    /// Encode a symbol given its range within the probability space.
    ///
    /// Arguments:
    ///     * `start` (u32): Lower bound of the symbol's cumulative frequency.
    ///     * `end` (u32): Upper bound of the symbol's cumulative frequency.
    ///     * `denominator` (u32): Total sum of frequencies (the scale).
    ///
    /// Raises:
    ///     ValueError: If the arguments are inconsistent
    ///         (e.g. `end < start` or `denominator < end`).
    fn encode(&mut self, start: u32, end: u32, denominator: u32) -> PyResult<()> {
        let mid = end
            .checked_sub(start)
            .ok_or_else(|| PyValueError::new_err("end must be >= start"))?;

        let after = denominator
            .checked_sub(end)
            .ok_or_else(|| PyValueError::new_err("denominator must be >= end"))?;

        self.inner.encode_interval(Interval::new(start, mid, after));

        Ok(())
    }

    /// Finalize the encoding process and return the compressed data.
    ///
    /// After calling this method, the encoder is reset and cannot encode
    /// further symbols until reused.
    ///
    /// Returns:
    ///     bytes: The encoded byte string.
    fn read(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.inner)
            .finalize()
            .into_iter()
            .collect::<Vec<u8>>()
    }
}

/// An arithmetic decoder for decompressing encoded sequences.
///
/// This class consumes a byte stream produced by [`ArithmeticEncoder`]
/// and reconstructs the original sequence of symbols given their weights.
#[pyclass]
pub struct ArithmeticDecoder {
    inner: ArithmeticDecoder32<std::vec::IntoIter<u8>>,
}

#[pymethods]
impl ArithmeticDecoder {
    /// Create a new decoder from a sequence of encoded bytes.
    ///
    /// Arguments:
    ///     * `bytes` (bytes): The compressed data produced by
    ///       [`ArithmeticEncoder.read`].
    ///
    /// Returns:
    ///     ArithmeticDecoder: A decoder initialized with the encoded stream.
    #[new]
    fn new(bytes: &[u8]) -> PyResult<Self> {
        // TODO: Can we do this without a copy?

        let inner = ArithmeticDecoder32::new(bytes.to_vec());
        Ok(Self { inner })
    }

    /// Decode the next symbol given its probability weights.
    ///
    /// Arguments:
    ///     * `weights` (List[int]): A list of non-negative integers representing
    ///       symbol frequencies. The sum of the weights is the denominator.
    ///
    /// Returns:
    ///     int: The index of the decoded symbol.
    fn decode_next(&mut self, weights: Vec<u32>) -> PyResult<u32> {
        let symbol_idx = self.inner.decode_by_weights(weights);

        Ok(symbol_idx as u32)
    }
}

/// Arithmetic coding in Python, powered by Rust.
///
/// This module provides a fast implementation of arithmetic encoding
/// and decoding through PyO3 bindings to the Rust `arithmetify` crate.
///
/// Arithmetic coding is a form of entropy coding used in lossless data
/// compression. Instead of assigning each symbol a fixed-length code,
/// it represents a sequence of symbols as a single fractional value
/// within the interval [0, 1).
///
/// Main classes:
///     * `ArithmeticEncoder`: Incrementally encodes symbols given their
///       probability ranges, and produces a compressed byte string.
///     * `ArithmeticDecoder`: Reconstructs the original sequence of symbols
///       from the encoded bytes, given the same probability weights.
///
/// Example:
///     >>> from arithmetipy import ArithmeticEncoder, ArithmeticDecoder
///     >>> alphabet_size = 3
///     >>> seq = [0, 1, 2, 1, 1, 0, 1, 2]
///     >>> encoder = ArithmeticEncoder()
///     >>> for symbol in seq:
///     ...     encoder.encode(symbol, symbol+1, alphabet_size)
///     >>> encoded = encoder.read()
///     >>> decoder = ArithmeticDecoder(encoded)
///     >>> [decoder.decode_next([1]*alphabet_size) for _ in seq]
///     [0, 1, 2, 1, 1, 0, 1, 2]
#[pymodule]
fn arithmetipy(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ArithmeticEncoder>()?;
    m.add_class::<ArithmeticDecoder>()?;
    Ok(())
}
