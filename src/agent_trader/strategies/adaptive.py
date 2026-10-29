"""Versioned extension point for controlled autonomous experiments.

This filter can reject a plan. It cannot approve orders or alter engine limits.
"""

VERSION = "baseline-v1"


def candidate_filter(plan, context):
    return True
