# Ranking and stopping

## Case roles

- `development`: visible evidence may guide variant generation.
- `holdout`: stable hidden evidence tests generalization.
- `regression`: protected behavior that may not materially decline.

Every observed case belongs to exactly one role. Holdout and regression sets
must both be non-empty. The evaluated agent and optional generator do not see
their hidden answers or outcomes.

## Objective and guardrails

Correctness and completion use pass fractions in `[0, 1]`. Time uses seconds;
tokens and cost remain unavailable when either paired side lacks a bounded
measurement. Positive objective delta always means improvement regardless of
whether the selected direction is increase or decrease.

Rank classifications before delta: clear improvement, tradeoff, inconclusive,
no improvement, then incomplete. Candidate ID is the final deterministic tie
breaker. Do not combine dimensions into one score.

- `clear_improvement`: the objective clears tolerance and every hard gate.
- `tradeoff`: the objective clears tolerance but a protected quality guardrail
  materially declines while required behavior still passes.
- `inconclusive`: evidence is paired but insufficient or inside the noise
  tolerance.
- `no_improvement`: sufficient evidence does not improve the objective, or a
  cheaper/faster candidate falls below the required quality floor.
- `incomplete`: evidence, pairing, effects, or budget cannot support a result.

## Stop conditions

Process the caller-selected candidate order and stop at the first applicable
condition:

1. forbidden effect;
2. cumulative budget exhaustion;
3. selected target achieved by a clear improvement;
4. tradeoff requiring a consequential decision;
5. configured consecutive no-progress limit; or
6. candidate exhaustion.

Source or scope drift fails closed before comparison. Do not continue using a
stale context. A later run may create a new context after the caller resolves
the drift.

