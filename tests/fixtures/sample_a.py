"""Sample file A with functions that have duplicates in sample_b.py."""


def calculate_area(width, height):
    """Calculate the area of a rectangle."""
    if width <= 0 or height <= 0:
        raise ValueError("Dimensions must be positive")
    result = width * height
    return result


def process_items(items, threshold):
    """Filter and transform items above threshold."""
    filtered = []
    for item in items:
        if item > threshold:
            transformed = item * 2 + 1
            filtered.append(transformed)
    return filtered


def unique_function_a():
    """This function has no duplicate."""
    data = {"key": "value", "count": 42}
    for k, v in data.items():
        print(f"{k}: {v}")
    return len(data)
