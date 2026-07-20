def split_batches(output_count: int) -> list[int]:
    result = []
    while output_count:
        result.append(min(10, output_count))
        output_count -= result[-1]
    return result


def test_api_batch_limit():
    assert split_batches(3) == [3]
    assert split_batches(10) == [10]
    assert split_batches(23) == [10, 10, 3]
