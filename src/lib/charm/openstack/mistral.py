import collections
import socket
import subprocess

import charmhelpers.core.hookenv as hookenv
import charms_openstack.charm
import charms_openstack.ip as os_ip

# import charms_openstack.sdn.odl as odl
# import charms_openstack.sdn.ovs as ovs


class MistralCharm(charms_openstack.charm.HAOpenStackCharm):

    # Internal name of charm
    service_name = name = 'mistral'

    # First release supported
    release = 'mitaka'

    # List of packages to install for this charm
    packages = ['mistral-api', 'mistral-engine', 'mistral-executor', 'python-apt']

    api_ports = {
        'mistral-api': {
            os_ip.PUBLIC: 8989,
            os_ip.ADMIN: 8989,
            os_ip.INTERNAL: 8989,
        }
    }

    service_type = 'mistral'
    default_service = 'mistral-api'
    services = ['haproxy', 'mistral-api', 'mistral-engine', 'mistral-executor']

    # Note that the hsm interface is optional - defined in config.yaml
    required_relations = ['shared-db', 'amqp', 'identity-service']

    restart_map = {
        '/etc/mistral/mistral.conf': services,
        '/etc/mistral/policy.json': services,
        '/etc/mistral/logging.conf': services,
        '/etc/mistral/wf_trace_logging.conf': services}

    ha_resources = ['vips', 'haproxy']

    release_pkg = 'mistral-common'

    package_codenames = {
        'mistral-common': collections.OrderedDict([
            ('2', 'mitaka'),
            ('3', 'newton'),
            ('4', 'ocata'),
        ]),
    }

    sync_cmd = ['mistral-db-manage', '--config-file', '/etc/mistral/mistral.conf', 'upgrade', 'head']

    def db_sync(self):
        """Perform a database sync using the command defined in the
        self.sync_cmd attribute. The services defined in self.services are
        restarted after the database sync.
        """
        if not self.db_sync_done() and hookenv.is_leader():

            subprocess.check_call(['mistral-db-manage', '--config-file', '/etc/mistral/mistral.conf', 'upgrade', 'head'])
            subprocess.check_call(['mistral-db-manage', '--config-file', '/etc/mistral/mistral.conf', 'stamp', 'head'])
            subprocess.check_call(['mistral-db-manage', '--config-file', '/etc/mistral/mistral.conf', 'populate'])

            hookenv.leader_set({'db-sync-done': True})
            # Restart services immediately after db sync as
            # render_domain_config needs a working system
            self.restart_all()

    def get_amqp_credentials(self):
        return ('mistral', 'mistral')

    def get_database_setup(self):
        return [{
            'database': 'mistral',
            'username': 'mistral',
            'hostname': hookenv.unit_private_ip() },]

    @property
    def public_url(self):
        return super().public_url + "/v2"

    @property
    def admin_url(self):
        return super().admin_url + "/v2"

    @property
    def internal_url(self):
        return super().internal_url + "/v2"

