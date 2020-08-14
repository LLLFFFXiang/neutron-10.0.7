# coding=utf-8
# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os

from neutron_lib import constants
from oslo_config import cfg

from neutron.agent import securitygroups_rpc
from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.extensions import portbindings
from neutron.plugins.common import constants as p_constants
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2.drivers import mech_agent
from neutron.plugins.ml2.drivers.openvswitch.agent.common \
    import constants as a_const
from neutron.services.qos.drivers.openvswitch import driver as ovs_qos_driver


IPTABLES_FW_DRIVER_FULL = ("neutron.agent.linux.iptables_firewall."
                           "OVSHybridIptablesFirewallDriver")


class OpenvswitchMechanismDriver(mech_agent.SimpleAgentMechanismDriverBase):
    """Attach to networks using openvswitch L2 agent.

    The OpenvswitchMechanismDriver integrates the ml2 plugin with the
    openvswitch L2 agent. Port binding with this driver requires the
    openvswitch agent to be running on the port's host, and that agent
    to have connectivity to at least one segment of the port's
    network.
    """

    def __init__(self):
        # sg_enabled、hybrid_plug_required是布尔值，不必在意取值的细节
        sg_enabled = securitygroups_rpc.is_firewall_enabled()
        hybrid_plug_required = (not cfg.CONF.SECURITYGROUP.firewall_driver or
            cfg.CONF.SECURITYGROUP.firewall_driver in (
                IPTABLES_FW_DRIVER_FULL, 'iptables_hybrid')) and sg_enabled
        # vif_details的详细介绍参考第4章
        vif_details = {portbindings.CAP_PORT_FILTER: sg_enabled,
                       portbindings.OVS_HYBRID_PLUG: hybrid_plug_required}
        super(OpenvswitchMechanismDriver, self).__init__(
            # agent_type = AGENT_TYPE_OVS = 'Open vSwitch agent'
            constants.AGENT_TYPE_OVS,
            # vif_type = VIF_TYPE_OVS = 'ovs
            portbindings.VIF_TYPE_OVS,
            vif_details)
        ovs_qos_driver.register()

    def get_allowed_network_types(self, agent):
        return (agent['configurations'].get('tunnel_types', []) +
                [p_constants.TYPE_LOCAL, p_constants.TYPE_FLAT,
                 p_constants.TYPE_VLAN])

    def get_mappings(self, agent):
        return agent['configurations'].get('bridge_mappings', {})

    def check_vlan_transparency(self, context):
        """Currently Openvswitch driver doesn't support vlan transparency."""
        return False

    def try_to_bind_segment_for_agent(self, context, segment, agent):
        if self.check_segment_for_agent(segment, agent):
            context.set_binding(segment[api.ID],
                                self.get_vif_type(agent, context),
                                self.get_vif_details(agent, context))
            return True
        else:
            return False

    def get_vif_type(self, agent, context):
        caps = agent['configurations'].get('ovs_capabilities', {})
        if (any(x in caps.get('iface_types', []) for x
                in [a_const.OVS_DPDK_VHOST_USER,
                    a_const.OVS_DPDK_VHOST_USER_CLIENT]) and
            agent['configurations'].get('datapath_type') ==
            a_const.OVS_DATAPATH_NETDEV):
            return portbindings.VIF_TYPE_VHOST_USER
        return self.vif_type

    def get_vhost_mode(self, iface_types):
        # NOTE(sean-k-mooney): this function converts the ovs vhost user
        # driver mode into the qemu vhost user mode. If OVS is the server,
        # qemu is the client and vice-versa.
        if (a_const.OVS_DPDK_VHOST_USER_CLIENT in iface_types):
            return portbindings.VHOST_USER_MODE_SERVER
        return portbindings.VHOST_USER_MODE_CLIENT

    def get_vif_details(self, agent, context):
        vif_details = self._pre_get_vif_details(agent, context)
        self._set_bridge_name(context.current, vif_details)
        return vif_details

    @staticmethod
    def _set_bridge_name(port, vif_details):
        # REVISIT(rawlin): add BridgeName as a nullable column to the Port
        # model and simply check here if it's set and insert it into the
        # vif_details.

        def set_bridge_name_inner(bridge_name):
            vif_details[portbindings.VIF_DETAILS_BRIDGE_NAME] = bridge_name

        registry.notify(
            a_const.OVS_BRIDGE_NAME, events.BEFORE_READ,
            set_bridge_name_inner, port=port)

    def _pre_get_vif_details(self, agent, context):
        a_config = agent['configurations']
        vif_type = self.get_vif_type(agent, context)
        if vif_type != portbindings.VIF_TYPE_VHOST_USER:
            details = dict(self.vif_details)
            hybrid = portbindings.OVS_HYBRID_PLUG
            if hybrid in a_config:
                # we only override the vif_details for hybrid plugging set
                # in the constructor if the agent specifically requests it
                details[hybrid] = a_config[hybrid]
            return details
        else:
            sock_path = self.agent_vhu_sockpath(agent, context.current['id'])
            caps = a_config.get('ovs_capabilities', {})
            mode = self.get_vhost_mode(caps.get('iface_types', []))
            return {
                portbindings.CAP_PORT_FILTER: False,
                portbindings.OVS_HYBRID_PLUG: False,
                portbindings.VHOST_USER_MODE: mode,
                portbindings.VHOST_USER_OVS_PLUG: True,
                portbindings.VHOST_USER_SOCKET: sock_path
            }
        return self.vif_details

    @staticmethod
    def agent_vhu_sockpath(agent, port_id):
        """Return the agent's vhost-user socket path for a given port"""
        sockdir = agent['configurations'].get('vhostuser_socket_dir',
                                              a_const.VHOST_USER_SOCKET_DIR)
        sock_name = (constants.VHOST_USER_DEVICE_PREFIX + port_id)[:14]
        return os.path.join(sockdir, sock_name)
