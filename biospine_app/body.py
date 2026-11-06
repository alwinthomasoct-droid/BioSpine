"""Height / weight helpers (pure Python, no Django, easy to test)."""

HEIGHT_RANGE_CM = (50.0, 250.0)
WEIGHT_RANGE_KG = (15.0, 350.0)

CATEGORIES = {
    "under":   "Underweight",
    "healthy": "Healthy weight",
    "over":    "Overweight",
    "obese":   "Obesity range",
}


def clean_body(height, weight):
    """Returns (height_cm, weight_kg, error). Both values may be None (left empty)."""
    def num(v):
        if v in (None, ""):
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError("Please enter numbers only for height and weight.")
        if x != x or x in (float("inf"), float("-inf")):
            raise ValueError("Please enter numbers only for height and weight.")
        return x
    try:
        h, w = num(height), num(weight)
    except ValueError as e:
        return None, None, str(e)
    if (h is None) != (w is None):
        return None, None, "Please enter both height and weight."
    if h is None:
        return None, None, None
    if not HEIGHT_RANGE_CM[0] <= h <= HEIGHT_RANGE_CM[1]:
        return None, None, f"Height must be between {HEIGHT_RANGE_CM[0]:.0f} and {HEIGHT_RANGE_CM[1]:.0f} cm."
    if not WEIGHT_RANGE_KG[0] <= w <= WEIGHT_RANGE_KG[1]:
        return None, None, f"Weight must be between {WEIGHT_RANGE_KG[0]:.0f} and {WEIGHT_RANGE_KG[1]:.0f} kg."
    return round(h, 1), round(w, 1), None


def bmi_info(height_cm, weight_kg):
    """BMI = kg / m^2, with the standard adult (WHO) bands. Returns None when data is missing."""
    if not height_cm or not weight_kg:
        return None
    m = height_cm / 100.0
    bmi = weight_kg / (m * m)
    key = "under" if bmi < 18.5 else "healthy" if bmi < 25 else "over" if bmi < 30 else "obese"
    lo, hi = 18.5 * m * m, 24.9 * m * m          # weights that give a BMI of 18.5 .. 24.9 at this height
    if weight_kg < lo:
        gap = round(lo - weight_kg, 1)           # kg to gain to reach the healthy range
    elif weight_kg > hi:
        gap = round(-(weight_kg - hi), 1)        # negative = kg above the healthy range
    else:
        gap = 0.0
    return {"bmi": round(bmi, 1), "key": key, "category": CATEGORIES[key],
            "healthy_min_kg": round(lo, 1), "healthy_max_kg": round(hi, 1), "gap_kg": gap}
