# Ansible Vmware VM Floppy

Allow user to add / reconfigure floppy using vmware (ESXi, vSphere, vCenter and so on).

## Installing

```bash
ansible-galaxy collection install https://github.com/helviojunior/ansible-vmware-floppy.git
```

## Samples
```yaml
- name: Add/edit an empty floppy drive
  vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    type: none
  delegate_to: localhost

- name: Add/edit client connected floppy drive
  vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    type: client
  delegate_to: localhost

- name: Add/edit .flp file floppy drive
  vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    type: flp
    image_file: "[datastore1] base_new.flp"
    start_connected: true
  delegate_to: localhost

- name: Remove floppy drive
  vmware_guest_floppy:
    hostname: 10.0.1.20
    username: administrator@vsphere.local
    password: vmware
    validate_certs: no
    state: absent
  delegate_to: localhost
 ```