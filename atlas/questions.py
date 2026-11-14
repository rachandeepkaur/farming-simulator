"""Task 6b: the Drex question set. The LLM baseline gets the same questions.

Drex question types: "noul" (yes/no, returns P(yes)), "choice" (returns the
chosen key and a probability per option), "score".
"""

QUESTIONS: dict = {
    "recommended": {
        "type": "choice",
        "instructions": (
            "Which rotation strategy best fits this field, given its water budget, "
            "frost and heat exposure, groundwater trend and the farmer's priorities?"
        ),
        "criteria": {
            "existing": "Keep the existing rotation.",
            "cover_crop": "Keep the main crop and add a winter cover crop.",
            "drought_tolerant": "Switch to a drought-tolerant rotation.",
        },
    },
    "fits_water_budget": {
        "type": "noul",
        "instructions": "Does the recommended strategy fit within this field's water budget?",
        "criteria": {
            "true": "The irrigation it needs is within the sustainable irrigation supply.",
            "false": "It needs more irrigation than the sustainable supply, so it draws down groundwater.",
        },
    },
    "frost_risk": {
        "type": "choice",
        "instructions": "How much frost risk does the recommended strategy face here?",
        "criteria": {
            "low": "Frost is rare or the crops are frost tolerant.",
            "moderate": "Some frost days and some frost-sensitive crops.",
            "high": "Frequent frost and frost-sensitive crops.",
        },
    },
    "soil_benefit": {
        "type": "choice",
        "instructions": "What is the main soil benefit of the recommended strategy?",
        "criteria": {
            "nitrogen": "Adds nitrogen (legume cover).",
            "organic_matter": "Builds organic matter (more residue or deeper roots).",
            "erosion_control": "Mainly protects bare soil from erosion.",
            "none": "No meaningful soil benefit.",
        },
    },
    "needs_local_review": {
        "type": "noul",
        "instructions": (
            "Should a local advisor review this suggestion on site because the call is "
            "borderline or the data is thin (for example a fallback groundwater value)?"
        ),
    },
    # Farm view: soil pH. When this is yes the farm sends a tractor to lime the field.
    "needs_lime": {
        "type": "noul",
        "instructions": "Is this field's soil acidic enough that it should be limed before the next crop?",
        "criteria": {
            "true": "Soil pH is below about 6.0, where most of these crops lose yield.",
            "false": "Soil pH is 6.0 or higher, or not stated.",
        },
    },
    # Additions to the PRD's five: water fit for every strategy, so the field
    # card can compare all three without extra calls.
    "fit_existing": {
        "type": "noul",
        "instructions": "Does the existing rotation fit this field's water budget?",
    },
    "fit_cover_crop": {
        "type": "noul",
        "instructions": "Does the winter cover crop strategy fit this field's water budget?",
    },
    "fit_drought_tolerant": {
        "type": "noul",
        "instructions": "Does the drought-tolerant rotation fit this field's water budget?",
    },
}

BOOL_KEYS = [k for k, q in QUESTIONS.items() if q["type"] == "noul"]
CHOICE_KEYS = [k for k, q in QUESTIONS.items() if q["type"] == "choice"]
