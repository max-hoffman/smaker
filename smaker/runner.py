from backports import tempfile
import functools
import json
import os
import snakemake
from smaker import path_gen

def pretty_dump(blob):
    return json.dumps(blob, indent=4, sort_keys=True)

all_template = """\
import os
from smaker.utils import scrape_error_logs, scrape_final_targets
rule all:
    input: [ subworkflow_0(os.path.join(o,targ)) for o in config['final_paths'] for targ in scrape_final_targets(rules) ]

onerror:
    start = '%s\\nPrinting error log:' % ''.join(['=']*100)
    end = '\\nEnd of error log\\n%s' % ''.join(['=']*100)
    for error_log in scrape_error_logs(log):
        shell('echo "%s" && echo "%s\\n" && cat %s && echo "%s"' % (start, error_log, error_log, end))
"""

class SnakeRunner:
    def __init__(self, default_config, default_snakefile,cores=4):
        self.endpoints = {}
        self.default_snakefile = os.path.abspath(default_snakefile)
        self.cores = cores
        self.configfile = default_config
        with open(default_config, 'r') as cf:
            self.default_config = json.load(cf)

    def _merge_configs(self, base, overrides, nested_fields=['params', 'modules', 'sources']):
        for field in nested_fields:
            if overrides.get(field, None) != None:
                collection = overrides[field]
                if isinstance(collection, dict):
                    if base.get(field, None) == None: base[field] == {}
                    base[field].update(overrides[field])
                    del overrides[field]
                elif isinstance(collection, (tuple, list, set)):
                    if base.get(field, None) == None: base[field] == []
                    base[field] += list(collection)
                    del overrides[field]
        base.update(overrides)
        return base

    def run(self, endpoint, api_opts):
        config_overrides = self.endpoints.get(endpoint, None)
        assert config_overrides !=  None, 'Endpoint %s not defined' % endpoint

        if isinstance(config_overrides, dict): config_overrides = [config_overrides]
        assert len(config_overrides) > 0, "No configs found: %s" % endpoint

        subworkflow_configs = []
        for co in config_overrides:
            base_config = self.default_config.copy()
            workflow_config = self._merge_configs(base_config, co)
            workflow_config['final_paths'], workflow_config['run_wildcards'] = path_gen.config_to_targets([''], workflow_config)
            subworkflow_configs += [workflow_config]

        dryrun = api_opts.pop('dryrun', True)
        cwd = os.getcwd()

        print("Number of workflows: %s" % len(subworkflow_configs))
        if not api_opts.get('quiet', False):
            print('API options set:\n%s' % pretty_dump(api_opts))
            print('Workflow opts:\n%s' % pretty_dump(subworkflow_configs))

        with tempfile.TemporaryDirectory() as temp_dir:
            config_paths = []
            for idx, config in enumerate(subworkflow_configs):
                config_path = os.path.abspath(os.path.join(temp_dir, 'config%s.json' % idx))
                with open(config_path, 'w+') as f: json.dump(config, f)
                config_paths += [config_path]

            for config in config_paths:
                res = snakemake.snakemake(self.default_snakefile, configfile=config, dryrun=dryrun, **api_opts)
                assert res, 'Workflow failed'
                os.chdir(cwd)

    def add_endpoint(self, name, params):
        assert self.endpoints.get(name, None) == None, 'Tried to duplicate endpoint: %s' % name
        self.endpoints[name] = params

    @classmethod
    def run_undefined_endpoint(cls, configfile, snakefile, workflow_opts={}, api_opts={'cores': 2}):
        print('Running with dynamic workflow opts:\n%s' % pretty_dump(workflow_opts))
        sn = cls(configfile, snakefile)
        sn.add_endpoint('_undefined', workflow_opts)
        sn.run('_undefined', api_opts)

