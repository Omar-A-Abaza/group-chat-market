"""Pure LMSR functions for N outcomes. No database code.

q  = list of share counts per (live) outcome, b = liquidity parameter.
"""
import math


def _lse(xs):
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))


def cost(q, b):
    """C = b * ln(sum exp(q_i / b))."""
    return b * _lse([x / b for x in q])


def prices(q, b):
    """Softmax of q/b; sums to 1."""
    z = [x / b for x in q]
    m = max(z)
    e = [math.exp(x - m) for x in z]
    s = sum(e)
    return [x / s for x in e]


def shares_for_dollars(q, b, i, dollars):
    """Closed form: shares of outcome i that cost exactly `dollars`.

    delta = b*ln(S*(e^(X/b)-1) + e^(q_i/b)) - q_i, computed with a shift for stability.
    """
    if dollars <= 0:
        return 0.0
    z = [x / b for x in q]
    m = max(z)
    s = sum(math.exp(x - m) for x in z)
    qi = math.exp(z[i] - m)
    # b*ln(...) + b*m - q_i ; exp(X/b)-1 could overflow only for absurd X/b
    growth = math.expm1(min(dollars / b, 700))
    return b * (m + math.log(s * growth + qi)) - q[i]


def refund_for_shares(q, b, i, shares):
    """Money returned for selling `shares` of outcome i: C(before) - C(after)."""
    if shares <= 0:
        return 0.0
    after = list(q)
    after[i] -= shares
    return cost(q, b) - cost(after, b)


def initial_q_for_probs(probs, b):
    """q_i = b*ln(p_i), shifted so min is 0. Probabilities are normalised first."""
    total = sum(probs)
    if total <= 0 or any(p <= 0 for p in probs):
        raise ValueError("probabilities must be positive")
    raw = [b * math.log(p / total) for p in probs]
    lo = min(raw)
    return [x - lo for x in raw]


def eliminate(q, i):
    """Drop outcome i from the sum; the remaining prices renormalise to 1."""
    return q[:i] + q[i + 1:]
