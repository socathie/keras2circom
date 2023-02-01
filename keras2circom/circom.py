# Ref: https://github.com/zk-ml/uchikoma/blob/main/python/uchikoma/circom.py

from __future__ import annotations

import typing

import os
from os import path
import json
import numpy as np
from dataclasses import dataclass

import re

class SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'

circom_template_string = '''pragma circom 2.0.0;

{include}
template Model() {brace_left}
{signal}
{component}
{main}
{brace_right}

component main = Model();
'''

templates: typing.Dict[str, Template] = {

}

def parse_shape(shape: typing.List[int]):
    shape_str = ''
    for dim in shape:
        shape_str += '[{}]'.format(dim)
    return shape_str
    
def parse_index(shape: typing.List[int]):
    index_str = ''
    for i in range(len(shape)):
        index_str += '[i{}]'.format(i)
    return index_str

@dataclass
class Template:
    op_name: str
    fpath: str

    args: typing.Dict[str]

    input_names: typing.List[str]   = None
    input_dims: typing.List[int]    = None
    output_names: typing.List[str]  = None
    output_dims: typing.List[int]   = None

    def __str__(self):
        args_str = ', '.join(self.args)
        args_str = '(' + args_str + ')'
        return '{:>20}{:30} {}{}{}{} \t<-- {}'.format(
            self.op_name, args_str,
            self.input_names, self.input_dims,
            self.output_names, self.output_dims,
            self.fpath)

def file_parse(fpath):
    #  print('register circom file: ', fpath)
    with open(fpath, 'r') as f:
        lines = f.read().split('\n')

    lines = [l for l in lines if not l.strip().startswith('//')]
    lines = ' '.join(lines)

    lines = re.sub('/\*.*?\*/', 'IGN', lines)

    funcs = re.findall('template (\w+) ?\((.*?)\) ?\{(.*?)\}', lines)
    for func in funcs:
        op_name = func[0].strip()
        args = func[1].split(',')
        main = func[2].strip()
        assert op_name not in templates, \
            'duplicated template: {} in {} vs. {}'.format(
                    op_name, templates[op_name].fpath, fpath)

        signals = re.findall('signal (\w+) (\w+)(.*?);', main)
        infos = [[] for i in range(4)]
        for sig in signals:
            sig_types = ['input', 'output']
            assert sig[0] in sig_types, sig[1] + ' | ' + main
            idx = sig_types.index(sig[0])
            infos[idx*2+0].append(sig[1])

            sig_dim = sig[2].count('[')
            infos[idx*2+1].append(sig_dim)
        templates[op_name] = Template(
                op_name, fpath,
                [a.strip() for a in args],
                *infos)


def dir_parse(dir_path, skips=[]):
    names = os.listdir(dir_path)
    for name in names:
        if name in skips:
            continue

        fpath = path.join(dir_path, name)
        if os.path.isdir(fpath):
            dir_parse(fpath)
        elif os.path.isfile(fpath):
            if fpath.endswith('.circom'):
                file_parse(fpath)

# TODO: add back all typings and comments
@dataclass
class Signal:
    name: str
    shape: typing.List[int]
    value: typing.Any = None

    def inject_signal(self, comp_name: str):
        if self.value is not None:
            return 'signal input {}_{}{};\n'.format(
                    comp_name, self.name, parse_shape(self.shape))
        return ''
    
    def inject_main(self, comp_name: str, prev_comp_name: str = None, prev_signal: Signal = None):
        inject_str = ''
        if self.value is not None:
            for i in range(len(self.shape)):
                inject_str += '{}for (var i{} = 0; i{} < {}; i{}++) {{\n'.format(
                            ' '*i*4, i, i, self.shape[i], i)
            inject_str += '{}{}.{}{} <== {}_{}{};\n'.format(' '*(i+1)*4,
                        comp_name, self.name, parse_index(self.shape),
                        comp_name, self.name, parse_index(self.shape))
            inject_str += '}'*len(self.shape)+'\n'
            return inject_str
        
        if self.shape != prev_signal.shape:
            raise ValueError('shape mismatch: {} vs. {}'.format(self.shape, prev_signal.shape))
            
        for i in range(len(self.shape)):
            inject_str += '{}for (var i{} = 0; i{} < {}; i{}++) {{\n'.format(
                            ' '*i*4, i, i, self.shape[i], i)
        
        if 'activation' in comp_name or 're_lu' in comp_name or 'lambda' in comp_name:
            inject_str += '{}{}{}.{} <== {}.{}{};\n'.format(' '*(i+1)*4,
                        comp_name, parse_index(self.shape), self.name,
                        prev_comp_name, prev_signal.name, parse_index(self.shape))
        elif 'activation' in prev_comp_name or 're_lu' in prev_comp_name or 'lambda' in prev_comp_name:
            inject_str += '{}{}.{}{} <== {}{}.{};\n'.format(' '*(i+1)*4,
                        comp_name, self.name, parse_index(self.shape),
                        prev_comp_name, parse_index(self.shape), prev_signal.name)
        else:
            inject_str += '{}{}.{}{} <== {}.{}{};\n'.format(' '*(i+1)*4,
                        comp_name, self.name, parse_index(self.shape),
                        prev_comp_name, prev_signal.name, parse_index(self.shape))
        inject_str += '}'*len(self.shape)+'\n'
        return inject_str
    
    def inject_input_signal(self):
        if self.value is not None:
            raise ValueError('input signal should not have value')
        return 'signal input in{};\n'.format(parse_shape(self.shape))
    
    def inject_output_signal(self):
        if self.value is not None:
            raise ValueError('output signal should not have value')
        return 'signal output out{};\n'.format(parse_shape(self.shape))
    
    def inject_input_main(self, comp_name: str):
        if self.value is not None:
            raise ValueError('input signal should not have value')
        inject_str = ''
        for i in range(len(self.shape)):
            inject_str += '{}for (var i{} = 0; i{} < {}; i{}++) {{\n'.format(
                        ' '*i*4, i, i, self.shape[i], i)
        inject_str += '{}{}.{}{} <== in{};\n'.format(' '*(i+1)*4,
                    comp_name, self.name, parse_index(self.shape),
                    parse_index(self.shape))
        inject_str += '}'*len(self.shape)+'\n'
        return inject_str
    
    def inject_output_main(self, prev_comp_name: str, prev_signal: Signal):
        if self.value is not None:
            raise ValueError('output signal should not have value')
        if self.shape != prev_signal.shape:
            raise ValueError('shape mismatch: {} vs. {}'.format(self.shape, prev_signal.shape))
        
        if 'softmax' in prev_comp_name:
            return 'out[0] <== {}.out;\n'.format(prev_comp_name)
        
        inject_str = ''

        for i in range(len(self.shape)):
            inject_str += '{}for (var i{} = 0; i{} < {}; i{}++) {{\n'.format(
                        ' '*i*4, i, i, self.shape[i], i)
        
        if 're_lu' in prev_comp_name or 'lambda' in prev_comp_name:
            inject_str += '{}out{} <== {}{}.{};\n'.format(' '*(i+1)*4,
                        parse_index(self.shape),
                        prev_comp_name, parse_index(self.shape), prev_signal.name)
        else:
            inject_str += '{}out{} <== {}.{}{};\n'.format(' '*(i+1)*4,
                        parse_index(self.shape),
                        prev_comp_name, prev_signal.name, parse_index(self.shape))
        inject_str += '}'*len(self.shape)+'\n'
        return inject_str

@dataclass
class Component:
    name: str
    template: Template
    inputs: typing.List[Signal]
    outputs: typing.List[Signal]
    # optional args
    args: typing.Dict[str, typing.Any] = None
    weight_scale: float = 1.0
    bias_scale: float = 1.0

    def inject_include(self):
        return 'include "../{}";\n'.format(self.template.fpath)
    
    def inject_signal(self, prev_comp: Component = None, last_comp: bool = False):
        inject_str = ''
        for signal in self.inputs:
            if signal.value is None and prev_comp is None:
                inject_str += signal.inject_input_signal()
            elif signal.value is not None:
                inject_str += signal.inject_signal(self.name)
        for signal in self.outputs:
            if signal.value is None and last_comp is True:
                inject_str += signal.inject_output_signal()
        return inject_str
    
    def inject_component(self):
        if self.weight_scale == 1.0 and self.bias_scale == 1.0:
            raise ValueError('initiate weight_scale and bias_scale with Circuit.to_json first')
        if self.template.op_name == 'ReLU':
            inject_str = 'component {}{};\n'.format(self.name, parse_shape(self.outputs[0].shape))
            for i in range(len(self.outputs[0].shape)):
                inject_str += '{}for (var i{} = 0; i{} < {}; i{}++) {{\n'.format(
                            ' '*i*4, i, i, self.outputs[0].shape[i], i)
            inject_str += '{}{}{} = ReLU();\n'.format(' '*(i+1)*4,
                        self.name, parse_index(self.outputs[0].shape))
            inject_str += '}'*len(self.outputs[0].shape)+'\n'
            return inject_str
        
        if self.template.op_name == 'Poly':
            inject_str = 'component {}{};\n'.format(self.name, parse_shape(self.outputs[0].shape))
            for i in range(len(self.outputs[0].shape)):
                inject_str += '{}for (var i{} = 0; i{} < {}; i{}++) {{\n'.format(
                            ' '*i*4, i, i, self.outputs[0].shape[i], i)
            inject_str += '{}{}{} = Poly({});\n'.format(' '*(i+1)*4,
                        self.name, parse_index(self.outputs[0].shape), int(self.weight_scale))
            inject_str += '}'*len(self.outputs[0].shape)+'\n'
            return inject_str
        
        if 'scaledInvPoolSize' in self.template.args:
            self.args['scaledInvPoolSize'] = max(1.0, round(self.args['scaledInvPoolSize']*self.weight_scale))
        
        if 'scaledInv' in self.template.args:
            self.args['scaledInv'] = max(1.0, round(self.args['scaledInv']*self.weight_scale))

        return 'component {} = {}({});\n'.format(
            self.name, self.template.op_name, self.parse_args(self.template.args, self.args))
    
    def inject_main(self, prev_comp: Component = None, last_comp: bool = False):
        inject_str = ''
        for signal in self.inputs:
            if signal.value is not None:
                inject_str += signal.inject_main(self.name)
            elif prev_comp is None:
                inject_str += signal.inject_input_main(self.name)
            else:
                inject_str += signal.inject_main(self.name, prev_comp.name, prev_comp.outputs[0])
        if last_comp:
            for signal in self.outputs:
                inject_str += signal.inject_output_main(self.name, signal)
        return inject_str

    def to_json(self, weight_scale: float, current_scale: float):
        self.weight_scale = weight_scale
        self.bias_scale = self.calc_bias_scale(weight_scale, current_scale)
        print(self.name, self.weight_scale, self.bias_scale)

        json_dict = {}
        for signal in self.inputs:
            if signal.value is not None:
                if signal.name == 'bias' or signal.name == 'b':
                    print(signal.value)
                    json_dict.update({f'{self.name}_{signal.name}': list(map('{:.0f}'.format, (signal.value*self.bias_scale).round().flatten().tolist()))})
                else:
                    json_dict.update({f'{self.name}_{signal.name}': list(map('{:.0f}'.format, (signal.value*self.weight_scale).round().flatten().tolist()))})
        return json_dict
    
    def calc_bias_scale(self, weight_scale: float, current_scale: float):
        if self.template.op_name in ['ReLU', 'Flatten2D', 'ArgMax', 'MaxPooling2D', 'GlobalMaxPooling2D']:
            return current_scale
        if self.template.op_name == 'Poly':
            return current_scale * current_scale
        return weight_scale * current_scale
    
    @staticmethod
    def parse_args(template_args: typing.List[str], args: typing.Dict[str, typing.Any]):
        args_str = '{'+'}, {'.join(template_args)+'}'
        return args_str.format(**args)

@dataclass
class Circuit:
    components: typing.List[Component]

    def __init__(self):
        self.components = []

    def add_component(self, component: Component):
        self.components.append(component)
    
    def add_components(self, components: typing.List[Component]):
        self.components.extend(components)

    def inject_include(self):
        inject_str = []
        for component in self.components:
            inject_str.append(component.inject_include())
        return ''.join(set(inject_str))

    def inject_signal(self):
        inject_str = self.components[0].inject_signal()
        for i in range(1, len(self.components)):
            inject_str += self.components[i].inject_signal(self.components[i-1], i==len(self.components)-1)
        return inject_str

    def inject_component(self):
        inject_str = ''
        for component in self.components:
            inject_str += component.inject_component()
        return inject_str
    
    def inject_main(self):
        inject_str = self.components[0].inject_main()
        for i in range(1, len(self.components)):
            inject_str += self.components[i].inject_main(self.components[i-1], i==len(self.components)-1)
        return inject_str

    def to_circom(self):
        return circom_template_string.format(**{
            'include': self.inject_include(),
            'brace_left': '{',
            'signal': self.inject_signal(),
            'component': self.inject_component(),
            'main': self.inject_main(),
            'brace_right': '}',
        })

    def to_json(self):
        current_scale = 1.0
        weight_scale = self.calculate_scale()

        json_dict = {}

        for component in self.components:
            json_dict.update(component.to_json(weight_scale, current_scale))
            current_scale = component.calc_bias_scale(weight_scale, current_scale)
            print(component.name, current_scale)
        return json.dumps(json_dict)
    
    def calculate_scale(self):
        current_scale = 1.0
        weight_scale = 1.0
        while current_scale < 1e+64: # should be able to go up to 1e+75, but just in case
            current_scale = 1.0
            weight_scale *= 10
            for component in self.components:
                current_scale = component.calc_bias_scale(weight_scale, current_scale)
        if weight_scale == 10.0:
            raise Exception('Model too large to be converted to circom')
        return weight_scale/10