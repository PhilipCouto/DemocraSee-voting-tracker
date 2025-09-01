from django import template

register = template.Library()

@register.filter
def first_value(dictionary):
    """Get the first value from a dictionary"""
    if dictionary:
        return next(iter(dictionary.values()))
    return None