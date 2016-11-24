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


import amulet
import json
import subprocess
import time

from mistralclient.api import client as mistral_client


import charmhelpers.contrib.openstack.amulet.deployment as amulet_deployment
import charmhelpers.contrib.openstack.amulet.utils as os_amulet_utils

# Use DEBUG to turn on debug logging
u = os_amulet_utils.OpenStackAmuletUtils(os_amulet_utils.DEBUG)

workbook_definition = """
---
version: '2.0'

name: keystone_actions

workflows:
  get_first_keystone_project:
    type: direct

    output:
      project:
        id: <% $.project_id %>
        name: <% $.project_name %>

    tasks:
      get_project_id:
        action: keystone.projects_list
        publish:
          project_id: <% task(get_project_id).result[0].id %>
        on-success:
          - get_project_name

      get_project_name:
        action: keystone.projects_get project=<% $.project_id %>
        publish:
          project_name: <% task(get_project_name).result.name %>
"""


class MistralBasicDeployment(amulet_deployment.OpenStackAmuletDeployment):
    """Amulet tests on a basic Mistral deployment."""

    def __init__(self, series, openstack=None, source=None, stable=False):
        """Deploy the entire test environment."""
        super(MistralBasicDeployment, self).__init__(series, openstack,
                                                     source, stable)
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')
        exclude_services = ['percona-cluster', 'mongodb']
        self._auto_wait_for_status(exclude_services=exclude_services)

        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where mistral is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {'name': 'mistral'}
        other_services = [
            {'name': 'percona-cluster', 'constraints': {'mem': '3072M'}},
            {'name': 'rabbitmq-server'},
            {'name': 'keystone'},
            {'name': 'glance'},
        ]
        super(MistralBasicDeployment, self)._add_services(this_service,
                                                          other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'keystone:shared-db': 'percona-cluster:shared-db',
            'glance:shared-db': 'percona-cluster:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:amqp': 'rabbitmq-server:amqp',
            'mistral:shared-db': 'percona-cluster:shared-db',
            'mistral:identity-service': 'keystone:identity-service',
            'mistral:amqp': 'rabbitmq-server:amqp',
        }
        super(MistralBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        keystone_config = {'admin-password': 'openstack',
                           'admin-token': 'ubuntutesting'}
        configs = {'keystone': keystone_config}
        super(MistralBasicDeployment, self)._configure_services(configs)

    def _get_token(self):
        return self.keystone.service_catalog.catalog['token']['id']

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.mistral_sentry = self.d.sentry['mistral'][0]
        self.mysql_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.mistral_svcs = [
            'mistral-api', 'mistral-engine', 'mistral-executor']
        # Authenticate admin with keystone endpoint
        self.keystone = u.authenticate_keystone_admin(self.keystone_sentry,
                                                      user='admin',
                                                      password='openstack',
                                                      tenant='admin')
        mistral_ep = self.keystone.service_catalog.url_for(
            service_type='workflowv2',
            endpoint_type='publicURL')

        keystone_ep = self.keystone.service_catalog.url_for(
            service_type='identity',
            endpoint_type='publicURL')

        self.mclient = mistral_client.client(
            username='admin',
            mistral_url=mistral_ep,
            auth_url=keystone_ep,
            project_name='admin',
            api_key='openstack')

    def check_and_wait(self, check_command, interval=2, max_wait=200,
                       desc=None):
        waited = 0
        while not check_command() or waited > max_wait:
            if desc:
                u.log.debug(desc)
            time.sleep(interval)
            waited = waited + interval
        if waited > max_wait:
            raise Exception('cmd failed {}'.format(check_command))

    def _run_action(self, unit_id, action, *args):
        command = ["juju", "action", "do", "--format=json", unit_id, action]
        command.extend(args)
        print("Running command: %s\n" % " ".join(command))
        output = subprocess.check_output(command)
        output_json = output.decode(encoding="UTF-8")
        data = json.loads(output_json)
        action_id = data[u'Action queued with id']
        return action_id

    def _wait_on_action(self, action_id):
        command = ["juju", "action", "fetch", "--format=json", action_id]
        while True:
            try:
                output = subprocess.check_output(command)
            except Exception as e:
                print(e)
                return False
            output_json = output.decode(encoding="UTF-8")
            data = json.loads(output_json)
            if data[u"status"] == "completed":
                return True
            elif data[u"status"] == "failed":
                return False
            time.sleep(2)

    def test_100_services(self):
        """Verify the expected services are running on the corresponding
           service units."""
        u.log.debug('Checking system services on units...')

        service_names = {
            self.mistral_sentry: self.mistral_svcs,
        }

        ret = u.validate_services_by_name(service_names)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

        u.log.debug('OK')

    def test_mistral(self):
        u.log.debug('Removing test workbook if present')
        wbs = [wb.name for wb in self.mclient.workbooks.list()]
        if 'keystone_actions' in wbs:
            self.mclient.workbooks.delete('keystone_actions')
        u.log.debug('Creating test workbook')

        self.mclient.workbooks.create(workbook_definition)
        u.log.debug('Executing workbook')
        exec_id = self.mclient.executions.create(
            'keystone_actions.get_first_keystone_project').id
        for i in range(0, 20):
            _execution = self.mclient.executions.get(exec_id)
            u.log.debug('Execution status: {}'.format(_execution.state))
            if _execution.state == 'SUCCESS':
                break
            elif _execution.state == 'RUNNING':
                time.sleep(10)
                continue
            else:
                msg = "Unknown or failed execution stats {}".format(
                    _execution.state)
                amulet.raise_status(amulet.FAIL, msg=msg)
        else:
            msg = "Timed out waiting for execution to complete"
            amulet.raise_status(amulet.FAIL, msg=msg)

        exec_output = json.loads(_execution.output)
        if exec_output['project']['name'] == "services":
            u.log.debug('OK')
