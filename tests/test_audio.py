from bgm_factory.audio import correct_half_double_tempo


def test_correct_half_tempo_chooses_requested_neighborhood() -> None:
    assert correct_half_double_tempo(63.2, 126) == 126.4
    assert correct_half_double_tempo(125, 126) == 125
