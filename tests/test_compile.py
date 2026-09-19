import os
import re

import pytest

from jinja2 import UndefinedError
from jinja2.environment import Environment
from jinja2.loaders import DictLoader


def test_filters_deterministic(tmp_path):
    src = "".join(f"{{{{ {i}|filter{i} }}}}" for i in range(10))
    env = Environment(loader=DictLoader({"foo": src}))
    env.filters.update(dict.fromkeys((f"filter{i}" for i in range(10)), lambda: None))
    env.compile_templates(tmp_path, zip=None)
    name = os.listdir(tmp_path)[0]
    content = (tmp_path / name).read_text("utf8")
    expect = [f"filters['filter{i}']" for i in range(10)]
    found = re.findall(r"filters\['filter\d']", content)
    assert found == expect


def test_import_as_with_context_deterministic(tmp_path):
    src = "\n".join(f'{{% import "bar" as bar{i} with context %}}' for i in range(10))
    env = Environment(loader=DictLoader({"foo": src}))
    env.compile_templates(tmp_path, zip=None)
    name = os.listdir(tmp_path)[0]
    content = (tmp_path / name).read_text("utf8")
    expect = [f"'bar{i}': " for i in range(10)]
    found = re.findall(r"'bar\d': ", content)[:10]
    assert found == expect


def test_top_level_set_vars_unpacking_deterministic(tmp_path):
    src = "\n".join(f"{{% set a{i}, b{i}, c{i} = tuple_var{i} %}}" for i in range(10))
    env = Environment(loader=DictLoader({"foo": src}))
    env.compile_templates(tmp_path, zip=None)
    name = os.listdir(tmp_path)[0]
    content = (tmp_path / name).read_text("utf8")
    expect = [
        f"context.vars.update({{'a{i}': l_0_a{i}, 'b{i}': l_0_b{i}, 'c{i}': l_0_c{i}}})"
        for i in range(10)
    ]
    found = re.findall(
        r"context\.vars\.update\(\{'a\d': l_0_a\d, 'b\d': l_0_b\d, 'c\d': l_0_c\d\}\)",
        content,
    )[:10]
    assert found == expect
    expect = [
        f"context.exported_vars.update(('a{i}', 'b{i}', 'c{i}'))" for i in range(10)
    ]
    found = re.findall(
        r"context\.exported_vars\.update\(\('a\d', 'b\d', 'c\d'\)\)",
        content,
    )[:10]
    assert found == expect


def test_loop_set_vars_unpacking_deterministic(tmp_path):
    src = "\n".join(f"  {{% set a{i}, b{i}, c{i} = tuple_var{i} %}}" for i in range(10))
    src = f"{{% for i in seq %}}\n{src}\n{{% endfor %}}"
    env = Environment(loader=DictLoader({"foo": src}))
    env.compile_templates(tmp_path, zip=None)
    name = os.listdir(tmp_path)[0]
    content = (tmp_path / name).read_text("utf8")
    expect = [
        f"_loop_vars.update({{'a{i}': l_1_a{i}, 'b{i}': l_1_b{i}, 'c{i}': l_1_c{i}}})"
        for i in range(10)
    ]
    found = re.findall(
        r"_loop_vars\.update\(\{'a\d': l_1_a\d, 'b\d': l_1_b\d, 'c\d': l_1_c\d\}\)",
        content,
    )[:10]
    assert found == expect


def test_block_set_vars_unpacking_deterministic(tmp_path):
    src = "\n".join(f"  {{% set a{i}, b{i}, c{i} = tuple_var{i} %}}" for i in range(10))
    src = f"{{% block test %}}\n{src}\n{{% endblock test %}}"
    env = Environment(loader=DictLoader({"foo": src}))
    env.compile_templates(tmp_path, zip=None)
    name = os.listdir(tmp_path)[0]
    content = (tmp_path / name).read_text("utf8")
    expect = [
        f"_block_vars.update({{'a{i}': l_0_a{i}, 'b{i}': l_0_b{i}, 'c{i}': l_0_c{i}}})"
        for i in range(10)
    ]
    found = re.findall(
        r"_block_vars\.update\(\{'a\d': l_0_a\d, 'b\d': l_0_b\d, 'c\d': l_0_c\d\}\)",
        content,
    )[:10]
    assert found == expect


def test_if_branch_loads_before_store_resolves_context():
    # All branches store the name and the body reads it before storing. The
    # local must be initialized from the context (resolve), not to missing.
    env = Environment()
    src = (
        "{% if cond %}{{ a.b }}{% set a = 1 %}"
        "{% elif other %}{% set a = 2 %}"
        "{% else %}{% set a = 3 %}{% endif %}"
    )
    code = env.compile(src, raw=True)
    assert re.search(r"^l_0_a = resolve\('a'\)$", code, re.MULTILINE)
    assert not re.search(r"^l_0_a = missing$", code, re.MULTILINE)

    # Reading after the assignment in the same branch uses the branch value.
    src = (
        "{% if cond %}{% set a = 1 %}{{ a }}"
        "{% elif other %}{% set a = 2 %}{% else %}{% set a = 3 %}{% endif %}"
    )
    code = env.compile(src, raw=True)
    assert re.search(r"^l_0_a = missing$", code, re.MULTILINE)

    # The same applies inside loops and blocks, where the local lives in the
    # inner frame and must resolve/alias the outer value.
    src = (
        "{% for i in seq %}{% if cond %}{{ a }}{% set a = 1 %}"
        "{% elif other %}{% set a = 2 %}{% else %}{% set a = 3 %}{% endif %}"
        "{% endfor %}"
    )
    code = env.compile(src, raw=True)
    assert re.search(r"^l_1_a = resolve\('a'\)$", code, re.MULTILINE)

    src = (
        "{% block b %}{% if cond %}{{ a }}{% set a = 1 %}"
        "{% elif other %}{% set a = 2 %}{% else %}{% set a = 3 %}{% endif %}"
        "{% endblock %}"
    )
    code = env.compile(src, raw=True)
    assert re.search(r"^l_0_a = resolve\('a'\)$", code, re.MULTILINE)


def test_undefined_import_curly_name():
    env = Environment(
        loader=DictLoader(
            {
                "{bad}": "{% from 'macro' import m %}{{ m() }}",
                "macro": "",
            }
        )
    )

    # Must not raise `NameError: 'bad' is not defined`, as that would indicate
    # that `{bad}` is being interpreted as an f-string. It must be escaped.
    with pytest.raises(UndefinedError):
        env.get_template("{bad}").render()
