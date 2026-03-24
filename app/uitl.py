def split_into_two(value: str):
    parts = value.split(",")

    if len(parts) != 2:
        raise ValueError(f"Expected exactly 2 values separated by ',', got {len(parts)}")

    var1, var2 = parts
    return var1, var2