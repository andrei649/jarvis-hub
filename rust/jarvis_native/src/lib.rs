//! H11.2 — Jarvis native hot-path crate (PyO3).
//!
//! Rust-accelerated equivalents of `agents/core/native_fallback.py`. Built
//! host-side (`maturin build --release`); the pure-Python fallback is used when
//! this extension isn't present, so behavior is identical either way.
//!
//! NOTE: this file is **source only** — it is compiled host-side, not in CI.

use pyo3::prelude::*;

#[pyfunction]
fn cosine_similarity(a: Vec<f64>, b: Vec<f64>) -> f64 {
    let n = a.len().min(b.len());
    if n == 0 {
        return 0.0;
    }
    let mut dot = 0.0;
    let mut na = 0.0;
    let mut nb = 0.0;
    for i in 0..n {
        dot += a[i] * b[i];
        na += a[i] * a[i];
        nb += b[i] * b[i];
    }
    let na = na.sqrt().max(1e-9);
    let nb = nb.sqrt().max(1e-9);
    dot / (na * nb)
}

#[pyfunction]
fn top_k_similar(query: Vec<f64>, vectors: Vec<Vec<f64>>, k: usize) -> Vec<(usize, f64)> {
    let mut scored: Vec<(usize, f64)> = vectors
        .iter()
        .enumerate()
        .map(|(i, v)| (i, cosine_similarity(query.clone(), v.clone())))
        .collect();
    scored.sort_by(|x, y| y.1.partial_cmp(&x.1).unwrap_or(std::cmp::Ordering::Equal));
    scored.into_iter().take(k).collect()
}

#[pyfunction]
fn count_tokens(text: &str) -> usize {
    text.split_whitespace().count()
}

#[pymodule]
fn jarvis_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("BACKEND", "rust")?;
    m.add_function(wrap_pyfunction!(cosine_similarity, m)?)?;
    m.add_function(wrap_pyfunction!(top_k_similar, m)?)?;
    m.add_function(wrap_pyfunction!(count_tokens, m)?)?;
    Ok(())
}
