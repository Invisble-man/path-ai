from typing import Dict, List


def generate_compatibility_matrix(rfp_requirements: Dict, company_profile: Dict) -> List[Dict]:
    """
    Compares RFP requirements against company profile.
    Returns a structured compatibility matrix.
    """

    matrix = []

    for key, requirement in rfp_requirements.items():
        company_value = company_profile.get(key, None)

        is_match = False
        status = "Missing"

        if company_value is None:
            status = "Missing"
        elif isinstance(requirement, list):
            is_match = company_value in requirement
            status = "Pass" if is_match else "Fail"
        else:
            is_match = company_value == requirement
            status = "Pass" if is_match else "Fail"

        matrix.append({
            "requirement": key,
            "rfp_value": requirement,
            "company_value": company_value,
            "status": status,
            "eligible": is_match
        })

    return matrix


def calculate_compatibility_score(matrix: List[Dict]) -> float:
    """
    Returns a percentage score (0–100) based on Pass/Fail.
    """

    if not matrix:
        return 0.0

    passed = sum(1 for row in matrix if row["status"] == "Pass")
    return round((passed / len(matrix)) * 100, 2)


def detect_hard_failures(matrix: List[Dict]) -> List[Dict]:
    """
    Flags deal-breakers like certifications, set-aside eligibility, etc.
    """

    hard_fail_keys = [
        "sdvosb",
        "8a",
        "wosb",
        "hubzone",
        "sam_registered",
        "active_cage_code"
    ]

    failures = []

    for row in matrix:
        if row["requirement"] in hard_fail_keys and row["status"] == "Fail":
            failures.append(row)

    return failures


def summarize_eligibility(matrix: List[Dict]) -> Dict:
    """
    Returns high-level Go / No-Go summary.
    """

    hard_failures = detect_hard_failures(matrix)

    return {
        "go_no_go": "NO-GO" if hard_failures else "GO",
        "hard_failures": hard_failures,
        "score": calculate_compatibility_score(matrix)
    }