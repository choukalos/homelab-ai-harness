"""
Implementation of the Transformer's core algorithm, transcribed from the
whitepaper digest (digest_transformer.whitepaper.md). Then a verification
harness proving the implementation is correct.

Run: python3 transformer_from_digest.py
"""
import numpy as np

# ===========================================================================
# IMPLEMENTATION — each block cites the digest field it came from.
# ===========================================================================

# [DIGEST: algorithm.steps.1]  Attention(Q,K,V) = softmax(QK^T/sqrt(d_k)) V
def scaled_dot_product_attention(Q, K, V, mask=None):
    d_k = Q.shape[-1]
    scores = Q @ K.T                          # "dot products of Q with all K"
    scores = scores / np.sqrt(d_k)            # [DIGEST: gotchas.scaling]
    if mask is not None:                      # [DIGEST: algorithm.steps.3] causal
        scores = np.where(mask == 0, -1e9, scores)
    e = np.exp(scores - scores.max(axis=-1, keepdims=True))  # stable softmax
    weights = e / e.sum(axis=-1, keepdims=True)
    return weights @ V, weights               # "weighted sum of V"


# [DIGEST: algorithm.steps.2]  MultiHead = Concat(head_1..head_h) W_O
# [DIGEST: params]             h=8, d_model=512, d_k=d_v=64
class MultiHeadAttention:
    def __init__(self, d_model=512, h=8, seed=0):
        rng = np.random.default_rng(seed)
        self.h = h
        self.d_k = d_model // h               # [DIGEST: gotchas] d_k = d_model/h
        s = 1 / np.sqrt(d_model)
        # [DIGEST: data_structures] W_Qi in R^{d_model x d_k}, h of them
        # => total projection is (d_model, h*d_k) = (d_model, d_model)
        self.W_q = rng.normal(0, s, (d_model, d_model))
        self.W_k = rng.normal(0, s, (d_model, d_model))
        self.W_v = rng.normal(0, s, (d_model, d_model))
        self.W_o = rng.normal(0, 1/np.sqrt(self.d_k), (d_model, d_model))

    def __call__(self, X, mask=None):
        n = X.shape[0]
        # head_i = Attention(Q W_Qi, K W_Ki, V W_Vi)
        heads, wts = [], []
        for i in range(self.h):
            q = X @ self.W_q[:, i*self.d_k:(i+1)*self.d_k]
            k = X @ self.W_k[:, i*self.d_k:(i+1)*self.d_k]
            v = X @ self.W_v[:, i*self.d_k:(i+1)*self.d_k]
            o, w = scaled_dot_product_attention(q, k, v, mask)
            heads.append(o); wts.append(w)
        concat = np.stack(heads, axis=1).reshape(n, -1)   # Concat(head_1..head_h)
        return concat @ self.W_o, wts                     # ... W_O


# ===========================================================================
# VERIFICATION — properties the digest's invariants demand.
# ===========================================================================
def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return bool(cond)

ok = True
print("== Scaled Dot-Product Attention ==")
rng = np.random.default_rng(1)
n, d_k = 5, 8
Q = rng.normal(size=(n, d_k)); K = rng.normal(size=(n, d_k)); V = rng.normal(size=(n, d_k))
out, w = scaled_dot_product_attention(Q, K, V)
ok &= check("output shape == (n, d_v)", out.shape == (n, d_k))
ok &= check("weights are simplex: each row sums to 1",
            np.allclose(w.sum(axis=-1), 1.0, atol=1e-9))
ok &= check("weights are non-negative", (w >= 0).all())
# relevance: a query equal to key[0] should attend ~all to value[0]
Q2 = np.zeros((1, d_k)); Q2[0, 0] = 25.0        # strong match to key[0]
K2 = np.eye(d_k); V2 = np.arange(1, d_k + 1, dtype=float)  # value[0] = 1
out2, w2 = scaled_dot_product_attention(Q2, K2, V2)
ok &= check("query matching key[0] -> attends ~100% to value[0]",
            w2[0, 0] > 0.99 and out2[0] > 0.99 * V2[0])
# scaling sanity: larger d_k without scaling would saturate softmax
big = 256
Qb = rng.normal(size=(1, big)); Kb = rng.normal(size=(4, big)); Vb = rng.normal(size=(4, big))
_, wb = scaled_dot_product_attention(Qb, Kb, Vb)
ok &= check("scaling keeps softmax in a healthy (non-saturated) regime",
            wb.min() > 1e-4)   # with 1/sqrt(d_k), no near-zero weights

print("== Causal (decoder) masking ==")
n2 = 6
Qc = rng.normal(size=(n2, 4)); Kc = rng.normal(size=(n2, 4)); Vc = rng.normal(size=(n2, 4))
# lower-triangular mask: position i may attend to j <= i  [DIGEST: invariants.causal]
mask = np.tril(np.ones((n2, n2)))
_, wc = scaled_dot_product_attention(Qc, Kc, Vc, mask=mask)
future_blocked = np.all(wc[np.triu(np.ones((n2, n2)), k=1).astype(bool)] < 1e-6)
ok &= check("causal mask: row i has ~0 weight on all future positions", future_blocked)
ok &= check("causal mask: each row still sums to 1",
            np.allclose(wc.sum(axis=-1), 1.0, atol=1e-6))

print("== Multi-Head Attention ==")
d_model, h = 512, 8
mha = MultiHeadAttention(d_model, h, seed=2)
X = rng.normal(size=(10, d_model))
outm, _ = mha(X)
ok &= check("multi-head output dim == d_model (512)", outm.shape == (10, d_model))
ok &= check("8 heads, each d_k = d_model/8 = 64", mha.d_k == 64 and mha.h == 8)

print()
print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)