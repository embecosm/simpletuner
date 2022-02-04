#!/usr/bin/python3
import json;

class Flag:
    class FlagEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Flag):
                return {
                    'name': obj.name,
                    'flags': obj.values,
                    'state': obj.state,
                    'n_states': obj.n_states,
                    'exclusions': list(obj.exclusions),
                };

            # Let the base class default method raise the TypeError
            return json.JSONEncoder.default(self, obj)

    class FlagDecoder(json.JSONDecoder):
        def __init__(self, *args, **kwargs):
            json.JSONDecoder.__init__(self, object_hook=self.object_hook, *args, **kwargs)

        def object_hook(self, dct):
            if "name" in dct:
                flag = Flag(dct["name"], dct["flags"]);
                flag.state = dct["state"];
                flag.n_states = dct["n_states"];
                flag.exclusions = set(dct["exclusions"]);
                return flag;

            else:
                return dct;

    def __init__(self, name, values):
        self.state = 0;
        self.n_states = len(values);
        self.exclusions = set();
        self.values = values;

        # For diagnostic and identification purposes only
        self.name = name;

    def __repr__(self):
        SHOW_FLAGS = True;

        if SHOW_FLAGS:
            return "<Flag {}: state={}, n_states={}, n_exclusions={}, {{{}}}>"\
                .format(self.name, self.state, self.n_states, len(self.exclusions),
                        " ".join(self.values));
        else:
            return "<Flag {}: state={}, n_states={}, n_exclusions={}>"\
                .format(self.name, self.state, self.n_states, len(self.exclusions));

    def __str__(self):
        return self.values[self.state];

    def all_states(self):
        return list([i for i in range(self.n_states)]);

    def valid_states(self):
        return list(filter(lambda s: s not in self.exclusions,
                           [i for i in range(self.n_states)]));

    def other_states(self):
        return list(filter(lambda s: s != self.state \
                           and s not in self.exclusions,
                           [i for i in range(self.n_states)]));
