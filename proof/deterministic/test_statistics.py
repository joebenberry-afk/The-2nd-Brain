from proof.runner.statistics import paired_bootstrap


def test_paired_bootstrap_is_reproducible_and_records_policy():
    result = paired_bootstrap([0, 1, 0, 1], [1, 1, 1, 1], seed=7, resamples=10_000)
    assert result.n == 4
    assert result.estimate == 0.5
    assert result.seed == 7
    assert result.resamples == 10_000
    assert result.lower <= result.estimate <= result.upper
