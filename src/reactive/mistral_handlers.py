# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess

import charms_openstack.charm as charm
import charms.reactive as reactive

# This charm's library contains all of the handler code associated with
# sdn_charm
import charm.openstack.mistral as mistral  # noqa

charm.use_defaults(
    'charm.installed',
    'amqp.connected',
    'shared-db.connected',
    'identity-service.connected',
    'identity-service.available',  # enables SSL support
    'config.changed',
    'update-status')


def horrible_hack_to_workaround_missing_package_files():
    import tarfile
    import shutil
    resource_tar = 'files/resources.tar'
    archive = tarfile.open(resource_tar)
    archive.extractall('/usr/lib/python2.7/dist-packages/mistral')
    shutil.copyfile(
        'files/mapping.json',
        '/usr/lib/python2.7/dist-packages/mistral/actions/openstack/mapping.json')


@reactive.when_not('config.rendered')
def mask_svc():
    mistral_svcs = ['mistral-api', 'mistral-engine', 'mistral-executor']
    for svc in mistral_svcs:
        subprocess.check_call(['systemctl', 'stop', svc])
        subprocess.check_call(['systemctl', 'mask', svc])


@reactive.when('config.rendered')
def unmask_svc():
    mistral_svcs = ['mistral-api', 'mistral-engine', 'mistral-executor']
    for svc in mistral_svcs:
        subprocess.check_call(['systemctl', 'unmask', svc])
        subprocess.check_call(['systemctl', 'start', svc])


@reactive.when('shared-db.available')
@reactive.when('identity-service.available')
@reactive.when('amqp.available')
def render_config(*args):
    """Render the configuration for charm when all the interfaces are
    available.
    """
    horrible_hack_to_workaround_missing_package_files()
    with charm.provide_charm_instance() as charm_class:
        charm_class.render_with_interfaces(args)
        charm_class.db_sync()
        charm_class.upgrade_if_available(args)
        charm_class.assess_status()
    reactive.set_state('config.rendered')


@reactive.when('ha.connected')
def cluster_connected(hacluster):
    """Configure HA resources in corosync"""
    with charm.provide_charm_instance() as charm_class:
        charm_class.configure_ha_resources(hacluster)
        charm_class.assess_status()
