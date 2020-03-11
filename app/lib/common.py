# !/usr/bin/env python
# -*- coding: utf-8 -*-
import json, struct, socket
import re
from datetime import datetime

from log_handle import Log

from app import Mongo
from app import redis_queue


def get_white_ip(white_ip):
    white_ip_list = []
    white_ip=white_ip.strip()
    if white_ip:
        white_ip = white_ip.split("\r\n")
        for ip in white_ip:
            white_ip_list += format_ip(ip)

    return white_ip_list


def is_ip(ip):
    patt = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$|^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}-\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    if not re.search(patt, ip):
        return False
    return True


def format_ip(ip_range):
    if "-" in ip_range:
        start_ip, end_ip = ip_range.split('-')

        ip_list = get_ip_list(start_ip, end_ip)
    else:
        ip_list = [ip_range]
    return ip_list


def delete_ip(task_id):
    redis_queue.del_key("scan_" + str(task_id))
    redis_queue.zremrangebyscore("ack_scan_" + str(task_id), "-INF", "+INF")


def add_ip(task_name, task_ips, task_ports, task_type, cron, white_ip=""):
    mongo_task = Mongo.coll['tasks']
    if mongo_task.find_one({"name": task_name, "task_status": {"$ne": "finish"}}):  # 有没完成的任务就不插入新任务了
        return False
    create_time = datetime.now()
    ips = format_ip(task_ips)

    try:
        Log().info("开始插入数据")
        pipe = redis_queue.pipe()

        insert_result = mongo_task.insert_one(
            {"name": task_name, "ip": task_ips, "port": task_ports, "diff_result": {"diff": 0},
             "task_status": "ready", "create_time": create_time,
             "task_type": task_type, "cron": cron})
        nmapscan_key = "scan_" + str(insert_result.inserted_id)
        white_ip = get_white_ip(white_ip)
        ips = set(ips) - set(white_ip)

        for ip in ips:
            sub_task_dict = {"base_task_id": str(insert_result.inserted_id), "ip": ip, "port": task_ports,
                             "task_status": "ready"}

            pipe.lpush(nmapscan_key, dict2str(sub_task_dict))

        # mongo_task.update_one({"_id": insert_result.inserted_id}, {"$set": {"sub_task": sub_task_list}})

        if insert_result:
            pipe.execute()
            Log().info("任务【%s】的数据插入完毕" % task_name)
            mongo_task.update_one({"_id": insert_result.inserted_id},
                                  {"$set": {"task_status": "running"}})
            return True

    except:
        Log().exception("插入数据失败")
        return False


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        pass

    try:
        import unicodedata
        unicodedata.numeric(s)
        return True
    except (TypeError, ValueError):
        pass
    return False


def ip_atoi(ip):
    return struct.unpack('!I', socket.inet_aton(ip))[0]


def ip_itoa(ip):
    return socket.inet_ntoa(struct.pack('!I', ip))


def get_ip_list(start_ip, end_ip):
    ip_list = []
    start_ip = ip_atoi(start_ip)
    end_ip = ip_atoi(end_ip) + 1
    for ip in range(start_ip, end_ip):
        ip_list.append(ip_itoa(ip))
    return ip_list


def dict2str(dictionary):
    try:
        if type(dictionary) == str:
            return dictionary
        return json.dumps(dictionary)
    except TypeError as e:
        Log().exception("conv dict failed : %s" % e)
