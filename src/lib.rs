use arithmetify::arith32::Interval;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use arithmetify::{
    ArithmeticDecoder as ArithmeticDecoder32, ArithmeticEncoder as ArithmeticEncoder32,
};

#[pyclass]
pub struct ArithmeticEncoder {
    inner: ArithmeticEncoder32,
}

#[pymethods]
impl ArithmeticEncoder {
    #[new]
    fn new() -> Self {
        Self {
            inner: ArithmeticEncoder32::new(),
        }
    }

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

    fn read(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.inner)
            .finalize()
            .into_iter()
            .collect::<Vec<u8>>()
    }
}

// Decoder
#[pyclass]
pub struct ArithmeticDecoder {
    inner: ArithmeticDecoder32<std::vec::IntoIter<u8>>,
}

#[pymethods]
impl ArithmeticDecoder {
    #[new]
    fn new(bytes: &[u8]) -> PyResult<Self> {
        // TODO: Can we do this without a copy?

        let inner = ArithmeticDecoder32::new(bytes.to_vec());
        Ok(Self { inner })
    }

    fn decode_next(&mut self, weights: Vec<u32>) -> PyResult<u32> {
        let symbol_idx = self.inner.decode_by_weights(weights);

        Ok(symbol_idx as u32)
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn arithmetipy(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ArithmeticEncoder>()?;
    m.add_class::<ArithmeticDecoder>()?;
    Ok(())
}
