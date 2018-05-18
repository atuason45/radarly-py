"""
Some functions and classes used internally.
"""

from .misc import flat


def instance_builder(cls, data, *args, **kwargs):
    """Build an object of a specific class. This function is scalable
    (if a list is set as argument, return a list of object; else just
    one object)
    """
    if not data:
        return data
    elif isinstance(data, dict):
        return cls(data, *args, **kwargs)
    elif isinstance(data, list):
        return [cls(item, *args, **kwargs) for item in data]
    raise TypeError


class CallableDict(dict):
    """Dict which can be called (proxy for __getitem__ method). This object has three
    additional features:
    * it converts all the keys of data source into string
    * the key before a search will be converted into a string
    * if the value asked is not found, the value will be returned
    """
    def __init__(self, *datas):
        super().__init__()
        for data in datas:
            data = dict([(str(key), data[key]) for key in data])
            self.update(data)

    def __missing__(self, key):
        return str(key)

    def __getitem__(self, key):
        key = str(key).replace('focus_', '')
        return super().__getitem__(key)

    def __call__(self, key):
        return self[key]


def id_to_value(data, dtype):
    """Based on some data, build a dictionary to translate an ID to a
    a label.

    Args:
        data (list[object]):
        dtype (str):
    Raises:
        ValueError: error raised if dtype is not 'focuses' or 'tags'
    Returns:
        dict: dictionary where the key are ID of the object and the value,
        the label.
    """
    if dtype == 'focuses':
        return dict([
            (str(focus['id']), focus['label']) for focus in data
        ])
    elif dtype == 'tags':
        return dict(flat([[
            (str(subtag['id']), subtag['value']) for subtag in tag.subtags
        ] for tag in data]))
    raise ValueError


def parse_struct_stat(stats):
    """Parse the structure of stats values in influencer data in order
    to return a pandas-compatible object.
    """
    data = dict()
    for stat in stats:
        for item in stats[stat]:
            for metric in item['counts']:
                data.setdefault(metric, dict())
                data[metric].update({
                    (stat, item['term']): item['counts'][metric]
                })
    return data


def parse_struct_interval(intervals):
    """Parse the response to get distribution which can be easily converted
    with pandas"""
    data = dict()
    for item in intervals:
        for metric in item['counts']:
            data.setdefault(metric, {})
            data[metric].update({item['date']: item['counts'][metric]})
    return data
