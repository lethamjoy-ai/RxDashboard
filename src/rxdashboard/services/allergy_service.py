from __future__ import annotations

# Deliberately small, explicit demonstration mapping. Unknown pairs remain Not Evaluated.
INGREDIENT_ALLERGENS = {"Amoxicillin": {"penicillin"}, "Lisinopril": {"ace inhibitor"}, "Ibuprofen": {"nsaid"}}


def allergy_indicator(medication_name: str, allergens: list[str]) -> str:
    known = INGREDIENT_ALLERGENS.get(medication_name, set())
    normalized = {item.strip().lower() for item in allergens}
    if not known:
        return "Not Evaluated"
    return "Potential Conflict" if known & normalized else "No Demonstrated Conflict"
