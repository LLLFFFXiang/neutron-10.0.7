# coding=utf-8
# Copyright (C) 2014,2015 VA Linux Systems Japan K.K.
# Copyright (C) 2014,2015 YAMAMOTO Takashi <yamamoto at valinux co jp>
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


from neutron.agent.common import ovs_lib
from neutron.plugins.ml2.drivers.openvswitch.agent.openflow \
    import br_cookie
from neutron.plugins.ml2.drivers.openvswitch.agent.openflow.ovs_ofctl \
    import ofswitch


class OVSAgentBridge(ofswitch.OpenFlowSwitchMixin,
                     br_cookie.OVSBridgeCookieMixin, ovs_lib.OVSBridge):
    """Common code for bridges used by OVS agent"""

    # 设置控制器，却调用del_controller
    def setup_controllers(self, conf):
        # 本质上就是调用命令行ovs-vsctl del-controller
        # OVS Agent实际上有两个模块可以选择，ovs-ofctl或者native
        # 这里教书的是ovs-ofctl，这个模块就是没有控制器
        # 所以setup controller就是删除控制器
        self.del_controller()

    def drop_port(self, in_port):
        self.install_drop(priority=2, in_port=in_port)
