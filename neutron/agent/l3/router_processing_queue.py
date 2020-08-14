# coding=utf-8
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
#

import datetime

from oslo_utils import timeutils
from six.moves import queue as Queue

# Lower value is higher priority
# PRC 消息，优先级最高（数字越小，优先级越高）
PRIORITY_RPC = 0
# 周期轮询锁获得的Router变更信息
PRIORITY_SYNC_ROUTERS_TASK = 1
# 这个与IPv6相关，本文不涉及IPv6，可以忽略，不影响L3 Agent的基本原理的理解
PRIORITY_PD_UPDATE = 2
DELETE_ROUTER = 1
PD_UPDATE = 2


class RouterUpdate(object):
    """Encapsulates a router update

    An instance of this object carries the information necessary to prioritize
    and process a request to update a router.
    """
    def __init__(self, router_id, priority,
                 action=None, router=None, timestamp=None, tries=5):
        # 优先级
        self.priority = priority
        # 变更消息到达L3 Agent的时间戳
        self.timestamp = timestamp
        # 如果没有传入时间戳，那么就以当前的时间戳为准
        if not timestamp:
            self.timestamp = timeutils.utcnow()
        # Router ID
        self.id = router_id
        # 变更消息中的"动作"枚举值
        self.action = action
        self.router = router
        self.tries = tries

    # 通过函数__lt__来定义排序算法，lt就是less than 的缩写
    def __lt__(self, other):
        """Implements priority among updates

        Lower numerical priority always gets precedence.  When comparing two
        updates of the same priority then the one with the earlier timestamp
        gets precedence.  In the unlikely event that the timestamps are also
        equal it falls back to a simple comparison of ids meaning the
        precedence is essentially random.
        """
        # 首先比较变更消息的优先级，优先级小的排名靠前
        if self.priority != other.priority:
            return self.priority < other.priority
        # 如果优先级相同，则比较变更消息到达的时间，先到达的排名靠前
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        # 如果以上两者皆相同，那就比较Router ID，这其实已经是放弃治疗了
        return self.id < other.id

    def hit_retry_limit(self):
        return self.tries < 0


class ExclusiveRouterProcessor(object):
    """Manager for access to a router for processing

    This class controls access to a router in a non-blocking way.  The first
    instance to be created for a given router_id is granted exclusive access to
    the router.

    Other instances may be created for the same router_id while the first
    instance has exclusive access.  If that happens then it doesn't block and
    wait for access.  Instead, it signals to the master instance that an update
    came in with the timestamp.

    This way, a thread will not block to wait for access to a router.  Instead
    it effectively signals to the thread that is working on the router that
    something has changed since it started working on it.  That thread will
    simply finish its current iteration and then repeat.

    This class keeps track of the last time that a router data was fetched and
    processed.  The timestamp that it keeps must be before when the data used
    to process the router last was fetched from the database.  But, as close as
    possible.  The timestamp should not be recorded, however, until the router
    has been processed using the fetch data.
    """
    # _masters是一个静态变量，它的数据类型是dictionary(字典)
    # 其中的key是router_id, value是class ExclusiveRouterProcessor对象实例
    _masters = {}
    _router_timestamps = {}

    def __init__(self, router_id):
        self._router_id = router_id

        if router_id not in self._masters:
            self._masters[router_id] = self
            self._queue = []

        self._master = self._masters[router_id]

    def _i_am_master(self):
        # 因为ERP1._master = ERP1, ERP2._master = ERP1, ERP3._master = ERP1,
        # 所以，只有ERP1才会return True
        return self == self._master

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self._i_am_master():
            del self._masters[self._router_id]

    def _get_router_data_timestamp(self):
        return self._router_timestamps.get(self._router_id,
                                           datetime.datetime.min)

    def fetched_and_processed(self, timestamp):
        """Records the data timestamp after it is used to update the router"""
        new_timestamp = max(timestamp, self._get_router_data_timestamp())
        #
        self._router_timestamps[self._router_id] = new_timestamp

    def queue_update(self, update):
        """Queues an update from a worker

        This is the queue used to keep new updates that come in while a router
        is being processed.  These updates have already bubbled to the front of
        the RouterProcessingQueue.
        """
        self._master._queue.append(update)

    def updates(self):
        """Processes the router until updates stop coming

        Only the master instance will process the router.  However, updates may
        come in from other workers while it is in progress.  This method loops
        until they stop coming.
        """
        # 对于EPR2、EPR3两个实例来说，它们的if条件不会满足
        if self._i_am_master():
            while self._queue:
                # Remove the update from the queue even if it is old.
                # 这里弹出了一个Router变更消息
                update = self._queue.pop(0)
                # Process the update only if it is fresh.
                # return update 暂时加上去
                # 暂时忘记下面的代码
                # 暂时不用管if
                # 记录当前时间戳
                # 判断时间戳，如果待处理的Router变更消息（update）更加靠后，
                # 那么就处理这个变更消息，否则就丢弃，在判断队列中的下一个消息
                if self._get_router_data_timestamp() < update.timestamp:
                    # 返回update，并且函数挂起在这里
                    yield update


class RouterProcessingQueue(object):
    """Manager of the queue of routers to process."""
    def __init__(self):
        # 包装了一个优先级队列（PriorityQueue）
        self._queue = Queue.PriorityQueue()

    def add(self, update):
        update.tries -= 1
        # 增加一个元素（update），优先级队列会自动排序
        self._queue.put(update)

    # L3 Agent就是 通过这个接口，获取Router的变化信息，也即遍历update
    def each_update_to_next_router(self):
        """Grabs the next router from the queue and processes

        This method uses a for loop to process the router repeatedly until
        updates stop bubbling to the front of the queue.
        """
        # 获取一个元素，优先级队列会返回优先级最靠前的那个元素
        next_update = self._queue.get()
        # with ...., 简单理解相当于rp = ExclusiveRouterProcessor(next_update.id)
        # 注意：rp是一个临时变量，当这个函数（each_update_to_next_router）退出时，
        # rp也就无效了
        with ExclusiveRouterProcessor(next_update.id) as rp:
            # Queue the update whether this worker is the master or not.
            # 将从优先级队列中获取的Router变更信息（next_update）扔个rp
            rp.queue_update(next_update)

            # Here, if the current worker is not the master, the call to
            # rp.updates() will not yield and so this will essentially be a
            # noop.
            # 从rp中再获取一个Router变更信息（update）
            for update in rp.updates():
                # 暂时忘记yield (rp, update)，暂时认为就是
                # return rp, update
                yield (rp, update)
