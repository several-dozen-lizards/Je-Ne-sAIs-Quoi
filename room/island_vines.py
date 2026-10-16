import math

VINE_STYLES = {'ivy', 'wisteria', 'rose', 'bramble', 'dead'}
VINE_LIMIT = 80
PATH_LIMIT = 32
POINT_LIMIT = 128


def validate_vines(items, size):
    if not isinstance(items, list) or len(items) > VINE_LIMIT:
        raise ValueError('An island supports up to 80 vine tangles')
    seen = set(); result = []
    def number(value, low, high):
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    for vine in items:
        if not isinstance(vine, dict):
            raise ValueError('Invalid vine')
        vid = vine.get('id'); seed = vine.get('seed'); paths = vine.get('paths')
        if (not isinstance(vid, str) or not 1 <= len(vid) <= 80 or vid in seen
                or vine.get('style') not in VINE_STYLES or type(seed) is not int or not 0 <= seed <= 4294967295
                or not number(vine.get('stemWidth'), .012, .12) or not number(vine.get('leafiness'), 0, 1)
                or not number(vine.get('branching'), 0, 1)
                or not isinstance(paths, list) or not 1 <= len(paths) <= PATH_LIMIT):
            raise ValueError('Invalid vine identity or growth settings')
        seen.add(vid); normalized_paths = []
        for path in paths:
            if not isinstance(path, list) or not 2 <= len(path) <= POINT_LIMIT:
                raise ValueError('Invalid vine path')
            normalized_path = []
            for point in path:
                if (not isinstance(point, list) or len(point) != 6
                        or not all(type(v) in (int, float) and math.isfinite(v) for v in point)
                        or abs(point[0]) > size/2+2 or abs(point[2]) > size/2+2 or not -12 <= point[1] <= 78
                        or not .8 <= math.sqrt(sum(v*v for v in point[3:])) <= 1.2):
                    raise ValueError('Invalid vine surface point')
                normalized_path.append(list(point))
            normalized_paths.append(normalized_path)
        result.append({key: vine[key] for key in ('id', 'style', 'seed', 'stemWidth', 'leafiness', 'branching')}
                      | {'paths': normalized_paths})
    return result
