"""Excel column labels shared by the full and lite workbook readers."""


def column(index):
    text = ""
    while index:
        index, digit = divmod(index - 1, 26)
        text = chr(65 + digit) + text
    return text
