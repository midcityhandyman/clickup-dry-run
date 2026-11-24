from dryrun.models import normalise_task, parse_automations


def autos(*raw):
    return parse_automations({"automations": list(raw)})


def tasks(*raw):
    return {t["id"]: normalise_task(t) for t in raw}


def auto(auto_id, trigger, actions, conditions=None, **extra):
    return {"id": auto_id, "trigger": trigger, "actions": actions,
            "conditions": conditions or [], **extra}
