"""Change only age wording in existing official onboarding posts."""
import re


OLD_AGE = re.compile(r'\b17\s*\+|\bat least 17\b|\b17 (?:or older|and older|years old)\b', re.IGNORECASE)
CURRENT_AGE = re.compile(r'\b18\s*\+|\bat least 18\b|\b18 (?:or older|and older|years old)\b', re.IGNORECASE)


def update_age_text(text):
    return OLD_AGE.sub(lambda match: match.group().replace('17', '18'), text)


def update_age_embed(data):
    """Preserve layout, images, links and every unrelated word."""
    import copy
    result = copy.deepcopy(data)
    for key in ('title', 'description'):
        if key in result:
            result[key] = update_age_text(result[key])
    for section, keys in (('footer', ('text',)), ('author', ('name',))):
        for key in keys:
            if key in result.get(section, {}):
                result[section][key] = update_age_text(result[section][key])
    for field in result.get('fields', []):
        for key in ('name', 'value'):
            if key in field:
                field[key] = update_age_text(field[key])
    return result


def embed_text(data):
    pieces = [data.get('title', ''), data.get('description', ''),
              data.get('footer', {}).get('text', ''), data.get('author', {}).get('name', '')]
    for field in data.get('fields', []):
        pieces.extend([field.get('name', ''), field.get('value', '')])
    return '\n'.join(pieces)
