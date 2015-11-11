# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Messages used in the math module."""

__author__ = [
    'johncox@google.com (John Cox)',
]

from common import safe_dom


RTE_MATH_MATHEMATICAL_FORMULA = """
This is the formula to display.
"""

# TODO(johncox): replace placeholder URL once target link is determined.
RTE_MATH_TYPE = safe_dom.assemble_text_message("""
This is the type of formula script.
""", 'https://code.google.com/p/course-builder/wiki/Dashboard')