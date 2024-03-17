"""Implements utilities for LEGEND Data Objects."""
from __future__ import annotations

import glob
import logging
import os
import string

import h5py

from .exceptions import LH5DecodeError

log = logging.getLogger(__name__)


def read_n_rows(name: str, h5f: str | h5py.File) -> int | None:
    """Look up the number of rows in an Array-like object.

    Return ``None`` if `name` is a :class:`Scalar` or a :class:`Struct`.
    """
    if not isinstance(h5f, h5py.File):
        h5f = h5py.File(h5f, "r")

    if not h5f or name not in h5f:
        msg = "not found"
        raise LH5DecodeError(msg, h5f, name)

    # get the datatype
    if "datatype" not in h5f[name].attrs:
        msg = "missing 'datatype' attribute"
        raise LH5DecodeError(msg, h5f, name)

    datatype = h5f[name].attrs["datatype"]
    datatype, shape, elements = parse_datatype(datatype)

    # scalars are dim-0 datasets
    if datatype == "scalar":
        return None

    # structs don't have rows
    if datatype == "struct":
        return None

    # tables should have elements with all the same length
    if datatype == "table":
        # read out each of the fields
        rows_read = None
        for field in elements:
            n_rows_read = read_n_rows(name + "/" + field, h5f)
            if not rows_read:
                rows_read = n_rows_read
            elif rows_read != n_rows_read:
                log.warning(
                    f"'{field}' field in table '{name}' has {rows_read} rows, "
                    f"{n_rows_read} was expected"
                )
        return rows_read

    # length of vector of vectors is the length of its cumulative_length
    if elements.startswith("array"):
        return read_n_rows(f"{name}/cumulative_length", h5f)

    # length of vector of encoded vectors is the length of its decoded_size
    if (
        elements.startswith("encoded_array")
        or datatype == "array_of_encoded_equalsized_arrays"
    ):
        return read_n_rows(f"{name}/encoded_data", h5f)

    # return array length (without reading the array!)
    if "array" in datatype:
        # compute the number of rows to read
        return h5f[name].shape[0]

    msg = f"don't know how to read datatype '{datatype}'"
    raise RuntimeError(msg)


def parse_datatype(datatype: str) -> tuple[str, tuple[int, ...], str | list[str]]:
    """Parse datatype string and return type, dimensions and elements.

    Parameters
    ----------
    datatype
        a LGDO-formatted datatype string.

    Returns
    -------
    element_type
        the datatype name dims if not ``None``, a tuple of dimensions for the
        LGDO. Note this is not the same as the NumPy shape of the underlying
        data object. See the LGDO specification for more information. Also see
        :class:`~.types.ArrayOfEqualSizedArrays` and
        :meth:`.lh5_store.LH5Store.read` for example code elements for
        numeric objects, the element type for struct-like  objects, the list of
        fields in the struct.
    """
    if "{" not in datatype:
        return "scalar", None, datatype

    # for other datatypes, need to parse the datatype string
    from parse import parse

    datatype, element_description = parse("{}{{{}}}", datatype)
    if datatype.endswith(">"):
        datatype, dims = parse("{}<{}>", datatype)
        dims = [int(i) for i in dims.split(",")]
        return datatype, tuple(dims), element_description

    return datatype, None, element_description.split(",")


def expand_vars(expr: str, substitute: dict[str, str] | None = None) -> str:
    """Expand (environment) variables.

    Note
    ----
    Malformed variable names and references to non-existing variables are left
    unchanged.

    Parameters
    ----------
    expr
        string expression, which may include (environment) variables prefixed by
        ``$``.
    substitute
        use this dictionary to substitute variables. Takes precedence over
        environment variables.
    """
    if substitute is None:
        substitute = {}

    # use provided mapping
    # then expand env variables
    return os.path.expandvars(string.Template(expr).safe_substitute(substitute))


def expand_path(
    path: str,
    substitute: dict[str, str] | None = None,
    list: bool = False,
    base_path: str | None = None,
) -> str | list:
    """Expand (environment) variables and wildcards to return absolute paths.

    Parameters
    ----------
    path
        name of path, which may include environment variables and wildcards.
    list
        if ``True``, return a list. If ``False``, return a string; if ``False``
        and a unique file is not found, raise an exception.
    substitute
        use this dictionary to substitute variables. Environment variables take
        precedence.
    base_path
        name of base path. Returned paths will be relative to base.

    Returns
    -------
    path or list of paths
        Unique absolute path, or list of all absolute paths
    """
    if base_path is not None and base_path != "":
        base_path = os.path.expanduser(os.path.expandvars(base_path))
        path = os.path.join(base_path, path)

    # first expand variables
    _path = expand_vars(path, substitute)

    # then expand wildcards
    paths = sorted(glob.glob(os.path.expanduser(_path)))

    if base_path is not None and base_path != "":
        paths = [os.path.relpath(p, base_path) for p in paths]

    if not list:
        if len(paths) == 0:
            msg = f"could not find path matching {path}"
            raise FileNotFoundError(msg)
        if len(paths) > 1:
            msg = f"found multiple paths matching {path}"
            raise FileNotFoundError(msg)

        return paths[0]

    return paths
