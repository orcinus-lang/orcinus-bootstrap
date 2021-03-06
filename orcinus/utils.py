# Copyright (C) 2019 Vasiliy Sheredeko
#
# This software may be modified and distributed under the terms
# of the MIT license.  See the LICENSE file for details.
import re


# noinspection PyPep8Naming
class cached_property(object):
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, cls=None):
        if instance is not None:
            result = instance.__dict__[self.func.__name__] = self.func(instance)
            return result
        return None  # ABC


def camel_case_to_lower_space(label):
    label = re.sub("([a-z])([A-Z])", "\g<1> \g<2>", label)
    return label.lower()
