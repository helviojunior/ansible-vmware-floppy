#!/usr/bin/python

# Copyright: (c) 2018, Terry Jones <terry.jones@example.org>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# Based on https://github.com/dericcrago/ansible/blob/6d6dea0881fe79e7b6c605a916266139dc4d15d7/lib/ansible/modules/cloud/vmware/vmware_guest.py
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import time

DOCUMENTATION = r'''
---
module: vmware_guest_floppy
short_description: Manages virtual machines in vCenter
description:
- Create new floppy disk.
- Modify, rename or remove a floppy disk.
version_added: '2.14.2'
author:
- Helvio Junior (@helviojunior)
notes:
- Tested on vSphere 7.0 U2
requirements:
- python >= 3.6
- PyVmomi
options:
  state:
    description:
    - Specify state of the floppy disk be in.
    - If C(state) is set to C(present) and VM exists, ensure the VM configuration conforms to task arguments.
    default: present
    choices: [ present, absent ]
  name:
    description:
    - Name of the VM to work with.
    - VM names in vCenter are not necessarily unique, which may be problematic, see C(name_match).
    - This parameter is case sensitive.
    required: yes
  name_match:
    description:
    - If multiple VMs matching the name, use the first or last found.
    default: 'first'
    choices: [ first, last ]
  uuid:
    description:
    - UUID of the instance to manage if known, this is VMware's unique identifier.
    - This is required if name is not supplied.
  type:
    description:
    - The type of floppy, valid options are C(none), C(client) or C(flp).
    - With C(none) the floppy will be disconnected but present.
    default: none
    choices: [ none, client, flp ]
  image_file:
    description:
    - The datastore path to the flp file to use, in the form of C([datastore1] path/to/file.flp). 
    - Required if type is set C(flp).
  start_connected:
    description:
    - The datastore path to the flp file to use, in the form of C([datastore1] path/to/file.flp). 
  esxi_hostname:
    description:
    - The ESXi hostname where the virtual machine will run.
    - This parameter is case sensitive.
  datacenter:
    description:
    - Destination datacenter for the deploy operation.
    - This parameter is case sensitive.
    default: ha-datacenter
extends_documentation_fragment: vmware.documentation

author:
    - Helvio Junior - M4v3r1ck (@helviojunior)
'''

EXAMPLES = r'''
- name: Add/edit an empty floppy drive
  helviojunior.vmware.vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    type: none
  delegate_to: localhost

- name: Add/edit client connected floppy drive
  helviojunior.vmware.vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    type: client
  delegate_to: localhost

- name: Add/edit .flp file floppy drive
  helviojunior.vmware.vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    type: flp
    image_file: "[datastore1] base_new.flp"
    start_connected: true
  delegate_to: localhost

- name: Remove floppy drive
  helviojunior.vmware.vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    state: absent
  delegate_to: localhost
  
'''

RETURN = r'''
instance:
    description: metadata about the virtual machine
    returned: always
    type: dict
    sample: None
'''

HAS_PYVMOMI = False
try:
    import pyVmomi
    from pyVmomi import vim, vmodl

    HAS_PYVMOMI = True
except ImportError:
    pass

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_text, to_native
from ansible.module_utils.vmware import (find_obj, gather_vm_facts, get_all_objs,
                                         compile_folder_path_for_object, serialize_spec,
                                         vmware_argument_spec, set_vm_power_state, PyVmomi)

class PyVmomiDeviceHelper(object):
    """ This class is a helper to create easily VMWare Objects for PyVmomiHelper """

    def __init__(self, module):
        self.module = module

    @staticmethod
    def create_sio_controller():
        sio_ctl = vim.vm.device.VirtualDeviceSpec()
        sio_ctl.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
        sio_ctl.device = vim.vm.device.VirtualSIOController()
        sio_ctl.device.deviceInfo = vim.Description()
        sio_ctl.device.busNumber = 0

        return sio_ctl

    @staticmethod
    def create_floppy(sio_ctl, floppy_type, flp_path=None):
        if isinstance(sio_ctl, vim.vm.device.VirtualDeviceSpec):
            sio_ctl = sio_ctl.device

        floppy_spec = vim.vm.device.VirtualDeviceSpec()
        floppy_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
        floppy_spec.device = vim.vm.device.VirtualFloppy()
        floppy_spec.device.controllerKey = sio_ctl.key
        floppy_spec.device.key = -1
        floppy_spec.device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
        floppy_spec.device.connectable.allowGuestControl = True
        floppy_spec.device.connectable.startConnected = (floppy_type != "none")
        if floppy_type in ["none", "client"]:
            floppy_spec.device.backing = vim.vm.device.VirtualFloppy.RemoteDeviceBackingInfo()
        elif floppy_type == "flp":
            floppy_spec.device.backing = vim.vm.device.VirtualFloppy.ImageBackingInfo(fileName=flp_path)

        return floppy_spec

    @staticmethod
    def is_equal_floppy(vm_obj, floppy_device, floppy_type, flp_path):
        if floppy_type == "none":
            return (isinstance(floppy_device.backing, vim.vm.device.VirtualFloppy.RemoteDeviceBackingInfo) and
                    floppy_device.connectable.allowGuestControl and
                    not floppy_device.connectable.startConnected and
                    (vm_obj.runtime.powerState != vim.VirtualMachinePowerState.poweredOn or not floppy_device.connectable.connected))
        elif floppy_type == "client":
            return (isinstance(floppy_device.backing, vim.vm.device.VirtualFloppy.RemoteDeviceBackingInfo) and
                    floppy_device.connectable.allowGuestControl and
                    floppy_device.connectable.startConnected and
                    (vm_obj.runtime.powerState != vim.VirtualMachinePowerState.poweredOn or floppy_device.connectable.connected))
        elif floppy_type == "flp":
            return (isinstance(floppy_device.backing, vim.vm.device.VirtualFloppy.ImageBackingInfo) and
                    floppy_device.backing.fileName == flp_path and
                    floppy_device.connectable.allowGuestControl and
                    floppy_device.connectable.startConnected and
                    (vm_obj.runtime.powerState != vim.VirtualMachinePowerState.poweredOn or floppy_device.connectable.connected))



class PyVmomiCache(object):
    """ This class caches references to objects which are requested multiples times but not modified """

    def __init__(self, content, dc_name=None):
        self.content = content
        self.dc_name = dc_name
        self.networks = {}
        self.clusters = {}
        self.esx_hosts = {}
        self.parent_datacenters = {}

    def find_obj(self, content, types, name, confine_to_datacenter=True):
        """ Wrapper around find_obj to set datacenter context """
        result = find_obj(content, types, name)
        if result and confine_to_datacenter:
            if self.get_parent_datacenter(result).name != self.dc_name:
                result = None
                objects = self.get_all_objs(content, types, confine_to_datacenter=True)
                for obj in objects:
                    if name is None or obj.name == name:
                        return obj
        return result

    def get_all_objs(self, content, types, confine_to_datacenter=True):
        """ Wrapper around get_all_objs to set datacenter context """
        objects = get_all_objs(content, types)
        if confine_to_datacenter:
            if hasattr(objects, 'items'):
                # resource pools come back as a dictionary
                # make a copy
                tmpobjs = objects.copy()
                for k, v in objects.items():
                    parent_dc = self.get_parent_datacenter(k)
                    if parent_dc.name != self.dc_name:
                        tmpobjs.pop(k, None)
                objects = tmpobjs
            else:
                # everything else should be a list
                objects = [x for x in objects if self.get_parent_datacenter(x).name == self.dc_name]

        return objects

    def get_network(self, network):
        if network not in self.networks:
            self.networks[network] = self.find_obj(self.content, [vim.Network], network)

        return self.networks[network]

    def get_cluster(self, cluster):
        if cluster not in self.clusters:
            self.clusters[cluster] = self.find_obj(self.content, [vim.ClusterComputeResource], cluster)

        return self.clusters[cluster]

    def get_esx_host(self, host):
        if host not in self.esx_hosts:
            self.esx_hosts[host] = self.find_obj(self.content, [vim.HostSystem], host)

        return self.esx_hosts[host]

    def get_parent_datacenter(self, obj):
        """ Walk the parent tree to find the objects datacenter """
        if isinstance(obj, vim.Datacenter):
            return obj
        if obj in self.parent_datacenters:
            return self.parent_datacenters[obj]
        datacenter = None
        while True:
            if not hasattr(obj, 'parent'):
                break
            obj = obj.parent
            if isinstance(obj, vim.Datacenter):
                datacenter = obj
                break
        self.parent_datacenters[obj] = datacenter
        return datacenter


class PyVmomiHelper(PyVmomi):
    def __init__(self, module):
        super(PyVmomiHelper, self).__init__(module)
        self.device_helper = PyVmomiDeviceHelper(self.module)
        self.configspec = None
        self.change_detected = False
        self.customspec = None
        self.cache = PyVmomiCache(self.content, dc_name=self.params['datacenter'])

    def gather_facts(self, vm):
        return gather_vm_facts(self.content, vm)

    def remove_floppy(self, vm_obj):

        if vm_obj and vm_obj.config.template:
            # Changing floppy settings on a template is not supported
            return

        floppy_device = self.get_vm_floppy_device(vm=vm_obj)
        if floppy_device is None:
            return

        floppy_spec = vim.vm.device.VirtualDeviceSpec()
        floppy_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.remove
        floppy_spec.device = floppy_device

        self.change_detected = True
        self.configspec.deviceChange.append(floppy_spec)

    def configure_floppy(self, vm_obj):

        if vm_obj and vm_obj.config.template:
            # Changing floppy settings on a template is not supported
            return

        floppy_spec = None
        floppy_device = self.get_vm_floppy_device(vm=vm_obj)
        floppy_type = self.module.params["type"]
        flp_path = self.module.params.get("image_file", None)
        if floppy_device is None:
            # Creating new floppy
            sio_device = self.get_vm_sio_device(vm=vm_obj)
            if sio_device is None:
                # Creating new SIO device
                sio_device = self.device_helper.create_sio_controller()
                self.change_detected = True
                self.configspec.deviceChange.append(sio_device)

            floppy_spec = self.device_helper.create_floppy(sio_ctl=sio_device, floppy_type=floppy_type, flp_path=flp_path)
            if vm_obj and vm_obj.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                floppy_spec.device.connectable.connected = (floppy_type != "none")
                floppy_spec.device.connectable.startConnected = (
                            floppy_type != "none" and self.module.params['start_connected'])

        elif not self.device_helper.is_equal_floppy(vm_obj=vm_obj, floppy_device=floppy_device, floppy_type=floppy_type, flp_path=flp_path):
            # Updating an existing floppy
            if floppy_type in ["client", "none"]:
                floppy_device.backing = vim.vm.device.VirtualFloppy.RemoteDeviceBackingInfo()
            elif floppy_type == "flp":
                floppy_device.backing = vim.vm.device.VirtualFloppy.ImageBackingInfo(fileName=flp_path)
            floppy_device.connectable = vim.vm.device.VirtualDevice.ConnectInfo()
            floppy_device.connectable.allowGuestControl = True
            floppy_device.connectable.startConnected = (
                    floppy_type != "none" and self.module.params['start_connected'])
            if vm_obj and vm_obj.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                floppy_device.connectable.connected = (floppy_type != "none")

            floppy_spec = vim.vm.device.VirtualDeviceSpec()
            floppy_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
            floppy_spec.device = floppy_device

        if floppy_spec:
            self.change_detected = True
            self.configspec.deviceChange.append(floppy_spec)

    def get_vm_sio_device(self, vm=None):
        if vm is None:
            return None

        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualSIOController):
                return device

        return None

    def get_vm_floppy_device(self, vm=None):
        if vm is None:
            return None

        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualFloppy):
                return device

        return None

    def apply_floppy_op(self, vm=None):
        # Configure the VM floppy
        self.configspec = vim.vm.ConfigSpec()
        self.configspec.deviceChange = []

        # VM already exists
        if self.module.params['state'] == 'absent':
            # destroy it
            self.remove_floppy(vm_obj=vm)
        elif self.module.params['state'] == 'present':
            if not self.module.params.get("type", None):
                self.module.fail_json(msg="type is mandatory")

            if self.module.params.get("type", None) not in ["none", "client", "flp"]:
                self.module.fail_json(msg="type is not valid. Permitted values: none, client, image_file")

            if self.module.params["type"] == "image_file" and not self.module.params.get("image_file", None):
                self.module.fail_json(msg="image_file is mandatory in case type is flp")

            self.configure_floppy(vm_obj=vm)
        else:
            # This should not happen
            raise AssertionError()

        change_applied = False

        # Only send VMWare task if we see a modification
        if self.change_detected:
            task = None
            try:
                task = vm.ReconfigVM_Task(spec=self.configspec)
            except vim.fault.RestrictedVersion as e:
                self.module.fail_json(msg="Failed to reconfigure virtual machine due to"
                                          " product versioning restrictions: %s" % to_native(e.msg))
            self.wait_for_task(task)
            change_applied = True

            if task.info.state == 'error':
                # https://kb.vmware.com/selfservice/microsites/search.do?language=en_US&cmd=displayKC&externalId=2021361
                # https://kb.vmware.com/selfservice/microsites/search.do?language=en_US&cmd=displayKC&externalId=2173
                return {'changed': change_applied, 'failed': True, 'msg': task.info.error.msg}

        vm_facts = self.gather_facts(vm)
        return {'changed': change_applied, 'failed': False, 'instance': vm_facts}

    @staticmethod
    def wait_for_task(task):
        # https://www.vmware.com/support/developer/vc-sdk/visdk25pubs/ReferenceGuide/vim.Task.html
        # https://www.vmware.com/support/developer/vc-sdk/visdk25pubs/ReferenceGuide/vim.TaskInfo.html
        # https://github.com/virtdevninja/pyvmomi-community-samples/blob/master/samples/tools/tasks.py
        while task.info.state not in ['error', 'success']:
            time.sleep(1)

def main():
    argument_spec = vmware_argument_spec()
    argument_spec.update(
        state=dict(type='str', default='present',
                   choices=['present', 'absent']),

        name=dict(type='str'),
        guest_id=dict(type='str'),
        image_file=dict(type='str'),
        type=dict(type='str', default=None),
        start_connected=dict(type='bool', default=False),
        name_match=dict(type='str', choices=['first', 'last'], default='first'),

        datacenter=dict(type='str', default='ha-datacenter'),
        esxi_hostname=dict(type='str'),
    )

    module = AnsibleModule(argument_spec=argument_spec,
                           supports_check_mode=True,
                           mutually_exclusive=[
                               ['cluster', 'esxi_hostname'],
                           ],
                           required_one_of=[
                               ['name', 'uuid'],
                           ],
                           )

    result = {'failed': False, 'changed': False}

    pyv = PyVmomiHelper(module)

    # Check if the VM exists before continuing
    vm = pyv.get_vm()

    if not vm:
        # If UUID is set, getvm select UUID, show error message accordingly.
        module.fail_json(msg="Unable to manage floppy disk for non-existing VM %s" % (module.params.get('uuid') or
                                                                                      module.params.get('name')))

    result = pyv.apply_floppy_op(vm)

    if 'failed' not in result:
        result['failed'] = False

    if result['failed']:
        module.fail_json(**result)
    else:
        module.exit_json(**result)


if __name__ == '__main__':
    main()