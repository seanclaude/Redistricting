import types


def attach_method(fxn, instance, myclass):
    f = types.MethodType(fxn, instance, myclass)
    setattr(instance, fxn.__name__, f)
