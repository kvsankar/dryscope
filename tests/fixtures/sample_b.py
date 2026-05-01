"""Sample file B with functions that are clones of sample_a.py."""


def compute_surface(w, h):
    """Compute the surface area of a rectangle."""
    if w <= 0 or h <= 0:
        raise ValueError("Width and height must be positive")
    area = w * h
    return area


def filter_values(values, cutoff):
    """Filter and double values above cutoff."""
    results = []
    for val in values:
        if val > cutoff:
            new_val = val * 2 + 1
            results.append(new_val)
    return results


def totally_different():
    """This function does something completely different."""
    import math

    angles = [0, 30, 45, 60, 90]
    for angle in angles:
        radians = math.radians(angle)
        print(f"sin({angle}) = {math.sin(radians):.4f}")
