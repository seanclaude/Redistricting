__author__ = 'sean'


# Add enumerations for Python 2.x, http://stackoverflow.com/questions/36932/how-can-i-represent-an-enum-in-python
def enum(**enums):
    return type('Enum', (), enums)

