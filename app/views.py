#!/usr/bin/env python
# coding: utf-8

import re
import json
from lib.log_handle import Log
from bson.json_util import dumps
from bson.objectid import ObjectId
from flask import request, render_template, redirect, url_for, session
from flask_wtf.csrf import CSRFError
from app.lib.validate import TaskValidate
from lib.login_handle import logincheck
from . import app, Mongo, scheduler, csrf
from app.lib.common import add_ip, delete_ip


@app.template_filter('strftime')
def _jinja2_filter_strftime(date):
    if date:
        return date.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return ""


@app.template_filter('list2str')
def _jinja2_filter_list2str(list_param):
    if isinstance(list_param, basestring):

        return list_param
    else:
        return ",".join(list_param)


# 设置
@app.route('/setting', methods=['get', 'post'])
@logincheck
@csrf.exempt
def Setting():
    if request.method == "POST":
        form_dict = {
            "scanning_num": "",
            "email_server": "",
            "sender": "",
            "email_pwd": "",
            "email_address": ""
        }

        for k, v in request.form.items():
            if k in form_dict:
                form_dict[k] = v
        form_dict["mail_enable"] = request.form.get("status")
        if form_dict["scanning_num"]:
            try:
                form_dict["scanning_num"] = int(form_dict["scanning_num"])
            except:
                return dumps({"status": "error", "content": "并发数只能是数字"})
        else:
            return dumps({"status": "error", "content": "并发数为空"})

        if form_dict["mail_enable"] == "on":
            if form_dict["email_server"] and form_dict["sender"] and form_dict["email_pwd"] and form_dict[
                "email_address"]:
                if "@" in form_dict["sender"] and "@" in form_dict["email_address"]:
                    if "," in form_dict["email_address"]:
                        form_dict["email_address"] = form_dict["email_address"].split(",")

                    if Mongo.coll["setting"] == 0:
                        insert_result = Mongo.coll['setting'].insert_one(form_dict)
                    else:
                        insert_result = Mongo.coll['setting'].update_one({}, {"$set": form_dict})
                    if insert_result:
                        return dumps({"status": "success", "content": "配置成功", "redirect": "/setting"})

            else:
                return dumps({"status": "error", "content": "邮件配置不能为空"})
        else:

            if Mongo.coll["setting"] == 0:
                insert_result = Mongo.coll['setting'].insert_one(
                    {"mail_enable": "off", "scanning_num": form_dict["scanning_num"]})
            else:
                Mongo.coll["setting"].delete_one({})
                insert_result = Mongo.coll['setting'].insert_one(
                    {"mail_enable": "off", "scanning_num": form_dict["scanning_num"]})
            if insert_result:
                return dumps({"status": "success", "content": "配置成功", "redirect": "/setting"})

        return dumps({"status": "error", "content": "添加任务失败"})
    else:

        setting_data = {}
        if Mongo.coll['setting'].count():
            setting_data = Mongo.coll["setting"].find_one()

        return render_template('setting.html', setting_data=setting_data)


# 搜索页
@app.route('/search')
@logincheck
def Search():
    q = request.args.get("q", "")
    dataset = []

    if ":" in q:
        q = q.split(":")

        regx = re.compile(q[1], re.IGNORECASE)
        if q[0] == "port":
            # search_result = Mongo.coll['scan_result'].find({"port": q[1]})
            search_result = Mongo.coll['scan_result'].aggregate(
                [{"$group": {"_id": "$ip_port", "data": {"$push": "$$ROOT"}}}, {'$match': {'data.port': int(q[1])}}],
                allowDiskUse=True)
        elif q[0] == "server":
            # search_result = Mongo.coll['scan_result'].find({"service": regx})
            search_result = Mongo.coll['scan_result'].aggregate(
                [{"$group": {"_id": "$ip_port", "data": {"$push": "$$ROOT"}}}, {'$match': {'data.service': regx}}],
                allowDiskUse=True)
        elif q[0] == "ip":
            search_result = Mongo.coll['scan_result'].aggregate(
                [{"$group": {"_id": "$ip_port", "data": {"$push": "$$ROOT"}}}, {'$match': {'data.ip': regx}}],
                allowDiskUse=True)
        elif q[0] == "soft":

            search_result = Mongo.coll['scan_result'].aggregate(
                [{"$group": {"_id": "$ip_port", "data": {"$push": "$$ROOT"}}}, {'$match': {'data.version_info': regx}}],
                allowDiskUse=True)
        else:
            return render_template('search.html', q=request.args.get("q", ""))
        for j in search_result:
            dataset.append([str(j['data'][0]['ip']), j['data'][0]['port'], str(j['data'][0].get('service', '')),
                            str(j['data'][0].get('version_info', '')),
                            str(j['data'][0]['create_time'])])

        return render_template('search.html', q=request.args.get("q", ""), dataset=dataset)
    return render_template('search.html', q=request.args.get("q", ""))


@app.route('/total')
@logincheck
def Total():
    task_id = request.args.get("task_id", "")

    task_name = request.args.get('task_name', '')

    count_info = {}
    ports_pie = []
    service_pie = []
    scan_result = []

    if task_id:
        draw = int(request.args.get("draw", ""))
        start = int(request.args.get("start", ""))
        length = int(request.args.get("length", ""))
        result = Mongo.coll['scan_result'].find({'base_task_id': ObjectId(task_id)}).sort("ip")
        for i in result[start:start + length]:
            scan_result.append(
                [str(i['ip']), i['port'], str(i.get('service', '')), str(i.get('version_info', '')),
                 str(i['create_time'])])

        resp = {
            'draw': draw,
            'recordsTotal': result.count(),
            'recordsFiltered': result.count(),
            'data': scan_result,
        }

        return json.dumps(resp)

    elif task_name:

        result = Mongo.coll['tasks'].find_one({"name": task_name, "task_status": "finish"}, sort=[("create_time", -1)])
        if result:
            task_id = result['_id']
        else:
            task_id = Mongo.coll['tasks'].find_one({"name": task_name}, sort=[("create_time", -1)])["_id"]
        ips_total = 0
        tmp = Mongo.coll['scan_result'].aggregate([{'$match': {'base_task_id': task_id}}, {"$group": {"_id": "$ip"}}])
        for i in tmp:
            ips_total += 1
        count_info['task_name'] = task_name
        count_info['task_id'] = task_id
        count_info['ips_total'] = ips_total

        result = Mongo.coll['scan_result'].find({'base_task_id': task_id})

        count_info['ports_total'] = result.count()

        result = Mongo.coll['scan_result'].aggregate(
            [{'$match': {'base_task_id': task_id}}, {"$group": {"_id": "$port", "value": {"$sum": 1}}},
             {"$sort": {"value": -1}}, {"$limit": 10}])
        for j in result:
            ports_pie.append({"name": str(j["_id"]), "value": j["value"]})

        result = Mongo.coll['scan_result'].aggregate(
            [{'$match': {'base_task_id': task_id}}, {"$group": {"_id": "$service", "value": {"$sum": 1}}},
             {"$sort": {"value": -1}}, {"$limit": 10}])
        for j in result:
            service_pie.append({"name": str(j["_id"]), "value": j["value"]})

    return render_template('total.html', count_info=count_info, ports_pie=ports_pie,
                           service_pie=service_pie, scan_result=scan_result)


@app.route('/diff_result', methods=['get'])
@logincheck
@csrf.exempt
def Diffresult():
    task_id = request.args.get('task_id', '')

    resp = {}
    add_ips, add_ports = [], []
    if task_id:
        cursor = Mongo.coll['tasks'].find_one({"_id": ObjectId(task_id)})
    if cursor and cursor['diff_result']['diff']:
        resp['title'] = cursor['create_time'].strftime('%Y-%m-%d')
        if 'add_ips' in cursor['diff_result'].keys() and len(cursor['diff_result']['add_ips']) > 0:
            resp['add_ips'] = cursor['diff_result']['add_ips']

        if 'add_ports' in cursor['diff_result'].keys() and len(cursor['diff_result']['add_ports']) > 0:

            for i in cursor['diff_result']['add_ports']:
                ip = i.split(":")[0]
                port = i.split(":")[1]
                c = Mongo.coll['scan_result'].find_one({"ip": ip, "port": int(port)}, sort=[("create_time", -1)])

                add_ports.append({"ip": i, "service": c['service'], "version_info": c['version_info'].strip()})
            resp['add_ports'] = add_ports
    return json.dumps(resp)


# 新增任务
@app.route('/add_task', methods=['get', 'post'])
@logincheck
@csrf.exempt
def Addtask():
    # 添加任务和拆分任务给flask做

    if request.method == "POST":

        form = TaskValidate(**request.form)
        validate_result = form.check("add_task")

        if validate_result["status"] == "success":
            if form.job_unit == "no":
                task_type = "normal"
            else:
                task_type = "loop"

            cron = " ".join([form.job_time, form.job_unit])
            if add_ip(form.task_name, form.task_ips, form.task_ports, task_type, cron, form.white_ip):
                if task_type == "loop":
                    form.job_time = float(form.job_time)
                    if form.job_unit == "days":
                        job = scheduler.add_job(func="app.lib.common:add_ip", id=form.task_name,
                                                args=(
                                                    form.task_name, form.task_ips, form.task_ports,
                                                    task_type, cron, form.white_ip),
                                                trigger="interval",
                                                days=form.job_time, replace_existing=True)
                    else:
                        job = scheduler.add_job(func="app.lib.common:add_ip", id=form.task_name,
                                                args=(
                                                    form.task_name, form.task_ips, form.task_ports,
                                                    task_type, cron, form.white_ip),
                                                trigger="interval",
                                                hours=form.job_time, replace_existing=True)

                return dumps({"status": "success", "content": "添加任务成功", "redirect": "/add_task"})
            else:
                return dumps({"status": "error", "content": "添加任务失败"})
        return dumps(validate_result)


    else:
        return render_template('add_task.html')


@app.route('/edit_task', methods=['get', 'post'])
@logincheck
@csrf.exempt
def Edittask():
    if request.method == "POST":

        form = TaskValidate(**request.form)
        validate_result = form.check("edit_task")

        if validate_result["status"] == "success":
            if form.job_unit == "no":
                task_type = "normal"
            else:
                task_type = "loop"

            cron = " ".join([form.job_time, form.job_unit])

            if task_type == "loop":
                form.job_time = float(form.job_time)
                if form.job_unit == "days":
                    job = scheduler.add_job(func="app.lib.common:add_ip", id=form.task_name,
                                            args=(
                                                form.task_name, form.task_ips, form.task_ports,
                                                task_type, cron, form.white_ip),
                                            trigger="interval",
                                            days=form.job_time, replace_existing=True)
                else:
                    job = scheduler.add_job(func="app.lib.common:add_ip", id=form.task_name,
                                            args=(
                                                form.task_name, form.task_ips, form.task_ports,
                                                task_type, cron, form.white_ip),
                                            trigger="interval",
                                            hours=form.job_time, replace_existing=True)
            else:
                return dumps({"status": "error", "content": "循环任务不能改成不循环", "redirect": "/edit_task"})
            return dumps({"status": "success", "content": "更新任务成功", "redirect": "/"})
        return dumps(validate_result)


    else:
        task_name = request.args.get('task_name', '')
        task_args = {
            "task_name": "",
            "task_ips": "",
            "task_ports": "",
            "task_type": "",
            "job_time": "",
            "job_unit": "",
            "white_ip": ""
        }
        job = scheduler.get_job(id=task_name)
        if job:
            task_args["task_name"], task_args["task_ips"], task_args["task_ports"], task_args[
                "task_type"], cron, task_args["white_ip"] = job.args

            task_args["job_time"], task_args["job_unit"] = cron.split(" ")
            task_args["white_ip"] = task_args["white_ip"].strip()
            # if task_args["white_ip"]:
            #     task_args["white_ip"]=task_args["white_ip"].split("\r\n")
            # else:
            #     task_args["white_ip"] =[]

        return render_template('edit_task.html', task_args=task_args)


@app.route('/resume_scheduler')
@logincheck
def Resume_scheduler():
    task_name = request.args.get('task_name', '')
    try:
        scheduler.resume_job(task_name)
        result = {"status": "success", "content": "启动循环成功"}
    except:
        Log().exception("启动循环出错")
        result = {"status": "error", "content": "启动循环出错"}

    return dumps(result)


@app.route('/pause_scheduler')
# @logincheck
def Pause_scheduler():
    task_name = request.args.get('task_name', '')
    try:
        scheduler.pause_job(task_name)
        result = {"status": "success", "content": "暂停循环成功"}
    except:
        Log().exception("暂停循环出错")
        result = {"status": "error", "content": "暂停循环出错"}

    return dumps(result)


# 任务列表页面
@app.route('/task')
@logincheck
def Task():
    # page = int(request.args.get('page', '1'))
    result = []
    cursor = Mongo.coll['tasks'].aggregate(
        [{"$sort": {"create_time": -1}}, {"$group": {"_id": "$name"}}])
    # {"$limit": page_size},
    # {"$skip": (page - 1) * page_size}])   #.sort('create_time', -1).limit(page_size).skip((page - 1) * page_size)
    # task_num = len(cursor._CommandCursor__data)

    for i in cursor:
        result.append(i)
    if result:
        return dumps(result)
    else:
        return dumps([])


@app.route('/')
@logincheck
def Index():
    result = []
    next_run_time = u"无"
    cursor = Mongo.coll['tasks'].aggregate(
        [{"$sort": {"create_time": -1}}, {"$group": {"_id": "$name"}}])
    for i in cursor:

        tasks = Mongo.coll['tasks'].find({'name': i['_id']}, sort=[("create_time", 1)])
        aps = scheduler.get_job(id=i['_id'])
        # 循环任务
        if aps:
            if aps.next_run_time:
                next_run_time = aps.next_run_time.strftime(
                    "%Y-%m-%d %H:%M:%S")
            else:
                next_run_time = "无"
            result.append(
                {"name": aps.args[0], "task_type": aps.args[3],
                 "ip": aps.args[1],
                 "port": aps.args[2], "length": tasks.count(),
                 "create_time": tasks[0]['create_time'], "cron": aps.args[4],
                 "task_status": tasks[tasks.count() - 1]['task_status'], "next_run_time": next_run_time
                 })
        # 一次性任务
        else:
            next_run_time = "无"

            result.append(
                {"name": i['_id'], "task_type": tasks[tasks.count() - 1]['task_type'],
                 "ip": tasks[tasks.count() - 1]['ip'],
                 "port": tasks[tasks.count() - 1]['port'], "length": tasks.count(),
                 "create_time": tasks[0]['create_time'], "cron": tasks[tasks.count() - 1].get("cron", "no"),
                 "task_status": tasks[tasks.count() - 1]['task_status'], "next_run_time": next_run_time
                 })

    return render_template('index.html', result=result)


# 任务详情页面
@app.route('/task_detail')
@logincheck
def TaskDetail():
    task_info = {}
    task_name = request.args.get('task_name', '')
    next_run_time = ""
    # page = int(request.args.get('page', '1'))

    tasks = Mongo.coll['tasks'].find({'name': task_name}, sort=[("create_time", 1)])
    # if (page - 1) * page_size < tasks.count():
    #     tasks = tasks.limit(page_size).skip((page - 1) * page_size)
    if tasks.count():
        aps = scheduler.get_job(id=task_name)
        if aps:
            if aps.next_run_time:

                next_run_time = aps.next_run_time.strftime(
                    "%Y-%m-%d %H:%M:%S")

            else:

                next_run_time = u"无"
        else:
            next_run_time = u"无"

        task_info = {"task_name": task_name, "task_type": tasks[0]['task_type'], "ip": tasks[0]['ip'],
                     "port": tasks[0]['port'], "scan_count": tasks.count(),
                     "create_time": tasks[0]['create_time'].strftime("%Y-%m-%d %H:%M:%S"), "cron": tasks[0]['cron'],
                     "next_run_time": next_run_time}

    return render_template('detail.html', task_info=task_info, tasks=tasks)


@app.route('/delete_task', methods=['get', 'post'])
@logincheck
def DeleteTask():
    task_name = request.form.get('task_name', '')
    if task_name:
        result = Mongo.coll['tasks'].find({'name': task_name})
        for doc in result:
            if Mongo.coll['tasks'].delete_one({'_id': doc['_id']}):

                if not Mongo.coll['scan_result'].delete_many({'base_task_id': doc['_id']}):
                    return 'fail'
            else:
                return 'fail'
        if scheduler.get_job(id=task_name):
            scheduler.delete_job(id=task_name)
        delete_ip(doc['_id'])
        return 'success'
    return 'fail'


@app.route('/login', methods=['get', 'post'])
def login_handle():
    if request.method == 'GET':
        return render_template('login.html')
    else:
        username = request.form.get('username')
        password = request.form.get('password')
        if username == app.config.get('ACCOUNT') and password == app.config.get('PASSWORD'):
            session['login'] = 'loginsuccess'
            return redirect(url_for('Index'))
        else:
            return redirect(url_for('login_handle'))


@app.route('/logout')
# @logincheck
def LoginOut():
    session['login'] = ''
    return redirect(url_for('login_handle'))


# @app.route('/404')
# def NotFound():
#     return render_template('404.html')


@app.route('/500')
def Error():
    return render_template('500.html')


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return redirect(url_for('Error'))


@app.errorhandler(404)
def page_not_found(error):
    return render_template('404.html')
