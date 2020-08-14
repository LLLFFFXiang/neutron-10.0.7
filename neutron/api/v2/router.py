# coding=utf-8
# Copyright (c) 2012 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from neutron_lib import constants
from neutron_lib.plugins import directory
from oslo_config import cfg
from oslo_service import wsgi as base_wsgi
import routes as routes_mapper
import six
import six.moves.urllib.parse as urlparse
import webob
import webob.dec
import webob.exc

from neutron.api import extensions
from neutron.api.v2 import attributes
from neutron.api.v2 import base
from neutron import manager
from neutron import policy
from neutron.quota import resource_registry
from neutron import wsgi


RESOURCES = {'network': 'networks',
             'subnet': 'subnets',
             'subnetpool': 'subnetpools',
             'port': 'ports'}
SUB_RESOURCES = {}
COLLECTION_ACTIONS = ['index', 'create']
MEMBER_ACTIONS = ['show', 'update', 'delete']
REQUIREMENTS = {'id': constants.UUID_PATTERN, 'format': 'json'}


class Index(wsgi.Application):
    def __init__(self, resources):
        self.resources = resources

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        metadata = {}

        layout = []
        for name, collection in six.iteritems(self.resources):
            href = urlparse.urljoin(req.path_url, collection)
            resource = {'name': name,
                        'collection': collection,
                        'links': [{'rel': 'self',
                                   'href': href}]}
            layout.append(resource)
        response = dict(resources=layout)
        content_type = req.best_match_content_type()
        body = wsgi.Serializer(metadata=metadata).serialize(response,
                                                            content_type)
        return webob.Response(body=body, content_type=content_type)


class APIRouter(base_wsgi.Router):

    @classmethod
    def factory(cls, global_config, **local_config):
        # 返回了APIRouter实例
        return cls(**local_config)

    def __init__(self, **local_config):
        # 创建mapper对象
        mapper = routes_mapper.Mapper()
        # 调用manager.init()函数加载插件
        manager.init()
        plugin = directory.get_plugin()
        ext_mgr = extensions.PluginAwareExtensionManager.get_instance()
        ext_mgr.extend_resources("2.0", attributes.RESOURCE_ATTRIBUTE_MAP)

        col_kwargs = dict(collection_actions=COLLECTION_ACTIONS,
                          member_actions=MEMBER_ACTIONS)

        # 一个内嵌函数，创建规则：Service API与处理函数之间的映射规则
        def _map_resource(collection, resource, params, parent=None):
            allow_bulk = cfg.CONF.allow_bulk
            # controller是一个函数，就是处理Service API所对应的函数
            # 函数base.create_resource的值赋给一个变量“controller”
            # 代码本来就写得繁杂，函数名、变量名还取得这么混淆
            controller = base.create_resource(
                collection, resource, plugin, params, allow_bulk=allow_bulk,
                parent=parent, allow_pagination=True,
                allow_sorting=True)
            path_prefix = None
            if parent:
                path_prefix = "/%s/{%s_id}/%s" % (parent['collection_name'],
                                                  parent['member_name'],
                                                  collection)
            # 重点关注：controller=controller
            mapper_kwargs = dict(controller=controller,
                                 requirements=REQUIREMENTS,
                                 path_prefix=path_prefix,
                                 **col_kwargs)
            # mapper.collection，这个就是构建映射规则
            # collection，是一个字符串，就是资源的复数形式，比如networks
            # resource，是一个字符串，就是资源的单数形式，比如network
            return mapper.collection(collection, resource,
                                     **mapper_kwargs)
        # 给mapper这个对象赋值
        mapper.connect('index', '/', controller=Index(RESOURCES))
        # 针对每一个核心资源（network、subnet等），调用_map_resource，构建映射规则
        for resource in RESOURCES:
            _map_resource(RESOURCES[resource], resource,
                          attributes.RESOURCE_ATTRIBUTE_MAP.get(
                              RESOURCES[resource], dict()))
            resource_registry.register_resource_by_name(resource)

        for resource in SUB_RESOURCES:
            _map_resource(SUB_RESOURCES[resource]['collection_name'], resource,
                          attributes.RESOURCE_ATTRIBUTE_MAP.get(
                              SUB_RESOURCES[resource]['collection_name'],
                              dict()),
                          SUB_RESOURCES[resource]['parent'])

        # Certain policy checks require that the extensions are loaded
        # and the RESOURCE_ATTRIBUTE_MAP populated before they can be
        # properly initialized. This can only be claimed with certainty
        # once this point in the code has been reached. In the event
        # that the policies have been initialized before this point,
        # calling reset will cause the next policy check to
        # re-initialize with all of the required data in place.
        policy.reset()
        # 调用父类__init__函数，将mapper赋值给成员变量map
        super(APIRouter, self).__init__(mapper)
