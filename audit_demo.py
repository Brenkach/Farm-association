"""Демонстраційна функція для Лаб. 6 (завдання 3): розрахунок вартості доставки.

СТАН PASS: Data-Driven рефакторинг, умови винесено в таблицю, CC = 2.
"""
from bisect import bisect_left

WEIGHT_LIMITS = (1, 5)                    # межі діапазонів, кг: до 1, до 5, понад 5
EXPRESS_FACTOR = {False: 1, True: 2}      # терміновість -> множник
PRICES = {                                # (регіон, номер діапазону ваги) -> ціна
    ("UA", 0): 50, ("UA", 1): 80, ("UA", 2): 150,
    ("EU", 0): 200, ("EU", 1): 350, ("EU", 2): 700,
    ("US", 0): 500, ("US", 1): 500, ("US", 2): 900,
}


def shipping_cost(region, weight, express):
    price = PRICES.get((region, bisect_left(WEIGHT_LIMITS, weight)))
    return price and price * EXPRESS_FACTOR[bool(express)]
# lookup table version
