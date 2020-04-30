#! /usr/bin/env python

from datetime import datetime, timedelta
import taskbased_sample_generator
import probabilistic_rewards_t
import bc_read_adversary
import bcth_prism_model
import numpy as np
import subprocess
import roslib
import yaml
import copy
import sys
import os

def timing_wrapper(func):
    def wrapper(*args,**kwargs):
        t = datetime.now()
        result = func(*args,**kwargs)
        t1 = datetime.now()
        print func, ' took time:', t1-t
        return result
    return wrapper


def get_battery_model():  ## for prism models, creates gocharge models in file
    # path = '/home/milan/workspace/strands_ws/src/battery_scheduler'
    path = roslib.packages.get_pkg_dir('battery_scheduler')
    if os.path.isfile(path+'/models/battery_charge_model.yaml') and os.path.isfile(path+'/models/battery_discharge_model.yaml'):
        with open (path+'/models/battery_charge_model.yaml', 'r') as f_charge:
            charge_model = yaml.load(f_charge)
        with open (path+'/models/battery_discharge_model.yaml', 'r') as f_discharge:
            discharge_model = yaml.load(f_discharge)
        print ('Battery Models Found at: ' +path+'/models/battery_discharge_model.yaml'+', '+ path+'/models/battery_charge_model.yaml' )

        for model in [charge_model, discharge_model]:
            for b in model:
                bnext_dict = model[b]
                total = np.sum(np.array(bnext_dict.values()))
                for bn in bnext_dict:
                    bnext_dict[bn] = float(bnext_dict[bn])/total
        return charge_model, discharge_model
    else:
        raise ValueError('No models found. First create battery model with probabilistic_battery_model.py')

@timing_wrapper
def get_simbattery_model(time_passed, charging, action):  # time_int in minutes
    path = roslib.packages.get_pkg_dir('battery_scheduler')
    # time_passed = 3*time_passed
    if bool(charging):
        if os.path.isfile(path+'/models/'+str(time_passed)+'battery_charge_model.yaml'):
            with open (path+'/models/'+str(time_passed)+'battery_charge_model.yaml', 'r') as f_charge:
                model = yaml.load(f_charge)
        else:
            subprocess.call('./probabilistic_simbattery_model.py '+ str(time_passed)+' '+str(charging),shell=True, cwd=path+'/src')
            with open (path+'/models/'+str(time_passed)+'battery_charge_model.yaml', 'r') as f_charge:
                model = yaml.load(f_charge)
    else:
        if os.path.isfile(path+'/models/'+str(time_passed)+'battery_discharge_model.yaml'):
            with open (path+'/models/'+str(time_passed)+'battery_discharge_model.yaml', 'r') as f_discharge:
                model = yaml.load(f_discharge)
        else:
            subprocess.call('./probabilistic_simbattery_model.py '+ str(time_passed)+' '+str(charging),shell=True, cwd=path+'/src')
            with open (path+'/models/'+str(time_passed)+'battery_discharge_model.yaml', 'r') as f_discharge:
                model = yaml.load(f_discharge)

    if action == 'go_charge':
        gocharge_model = dict ()
        for b, bdict in model.items():
            g_bdict = dict()
            if b == 99 or b == 100:
                g_bdict = copy.deepcopy(bdict)
            else:
                for bn, count in bdict.items():
                    gbn = int(round(0.99*bn))
                    if gbn > b:
                        if gbn in g_bdict:
                            g_bdict[gbn] += count
                        else:
                            g_bdict.update({gbn : count})
                    else:
                        if bn in g_bdict:
                            g_bdict[bn] += count
                        else:
                            g_bdict.update({bn : count})
            gocharge_model.update({b:g_bdict})
        model = copy.deepcopy(gocharge_model)
    
    for b in model:
        bnext_dict = model[b]
        total = np.sum(np.array(bnext_dict.values()))
        for bn in bnext_dict:
            bnext_dict[bn] = float(bnext_dict[bn])/total
    
    return model
  

class TaskBasedRHC:
    @timing_wrapper
    def __init__(self, horizon_hours, init_battery, init_charging, test_days, pareto_point, no_clusters='auto'):
        print "Initialising Task Based RHC"
        self.charge_model, self.discharge_model = get_battery_model()
        print "Initialising Rewards Model"
        self.pr = probabilistic_rewards_t.ProbabilisticRewards(test_days=test_days, no_clusters=no_clusters)
        self.no_int = self.pr.no_int 
        self.int_duration = self.pr.int_duration
        self.no_days = len(test_days)
        self.horizon_hours = 48
        self.horizon = horizon_hours*(60/self.int_duration) ## horizon in intervals
        self.req_pareto_point = pareto_point
        print "Generating Sample Tasks"
        self.samples = taskbased_sample_generator.SampleGenerator(test_days).samples
        print self.samples

        self.main_path = roslib.packages.get_pkg_dir('battery_scheduler')
        self.path_mod = self.main_path + '/models/'
        self.path_data = self.main_path + '/data/'

        ## For tracking plan
        self.actions = []
        self.obtained_rewards = []
        self.available_rewards = []
        self.matched_rewards = []
        self.battery = []
        self.charging = []
        self.time =[]
        self.pareto_point = []        
        self.timing_tracker = []
        self.simulate(init_battery, init_charging)

    
    def get_obtained_rew(self, ts, discharging_from, charging):
        if bool(charging):
            obtained_rew = 0
        else:
            completed_tasks = self.samples[(self.samples['end'] >= discharging_from) & (self.samples['end'] < ts)]
            if completed_tasks.empty:
                obtained_rew = 0
            else:
                obtained_rew = completed_tasks['priority'].sum()
        return obtained_rew

    def get_current_rew(self, ts, clusters=[]):
        tasks = self.samples[self.samples['start']<=ts]
        current_tasks = tasks[tasks['end']>=ts]
        if not current_tasks.empty:
            total_rew = current_tasks['priority'].sum()
            if clusters and total_rew!= 0:
                diff_min = np.inf
                cl_id = None
                for e,c in enumerate(clusters):
                    if diff_min > abs(total_rew - c):
                        diff_min = abs(total_rew - c)
                        cl_id = e
            return total_rew, cl_id, current_tasks
        
        else:
            return 0, None, current_tasks
        
    @timing_wrapper
    def get_current_battery(self, prev_battery, prev_charging, current_ts, charging_started, discharging_started, action):
        if bool(prev_charging):
            time_passed = int(round((current_ts - charging_started).total_seconds()/60))
        else:
            time_passed = int(round((current_ts - discharging_started).total_seconds()/60))
            
        model = get_simbattery_model(time_passed, prev_charging, action)
        
        if model[prev_battery]: 
            predict_b = []
            for j in range(3):
                nb = []
                prob = []
                for b,p in model[prev_battery].items():
                    nb.append(b)
                    prob.append(p)
                predict_b.append(np.random.choice(nb, p=prob))
            return int(np.mean(predict_b))
        else:   
            if bool(prev_charging):
                return 100
            else:
                return 0
            
    @timing_wrapper
    def simulate(self, init_battery, init_charging):
        print 'Simulating...'
        all_ts = (self.samples['start'].unique()).astype(datetime)/1000000000
        all_ts = [datetime.utcfromtimestamp(t) for t in all_ts]
        all_ts.sort()
        print all_ts
        unique_ts = []
        for e, t in enumerate(all_ts):
            if e == 0:
                unique_ts.append(t)
            else:
                if t - all_ts[e-1] > timedelta(minutes=5): ## New task once every 5 mins - to reduce data points
                    unique_ts.append(t)

        charging_from = discharging_from = unique_ts[0]
        battery = init_battery
        charging = init_charging 
        initial_tasks =  self.samples[self.samples['start'] == unique_ts[0]]
        task_end = initial_tasks['end'].max()
        for e, ts in enumerate(unique_ts):
            self.iter_tracker = []
            print "Task ", e+1, "/", len(unique_ts), "......."
            lr_t = datetime.now()
            probt, probm, rews = self.pr.get_rewards_model_at(ts)
            lr_t = datetime.now() - lr_t
            self.iter_tracker.append(lr_t)
            cs_t = datetime.now()
            current_rew, clid, current_tasks = self.get_current_rew(ts, clusters=rews)
            cs_t = datetime.now() - cs_t
            self.iter_tracker.append(cs_t)
            if e!= 0:
                if charging == 0 and task_end + timedelta(minutes=5) < ts:
                    obtained_rew = self.get_obtained_rew(task_end + timedelta(minutes=5), discharging_from, charging)
                    self.obtained_rewards.append(obtained_rew)
                    
                    battery = self.get_current_battery(battery, charging, task_end + timedelta(minutes=5), charging_from, discharging_from, action)

                    ## Adding nil task where reward seen is 0.
                    pmodel = self.obtain_prism_model(probt, probm, rews, battery, charging, None)

                    action = self.get_policy_action(pmodel)
                    
                    self.time.append(task_end + timedelta(minutes=5))
                    self.battery.append(battery)
                    self.charging.append(charging)
                    self.actions.append(action)
                    self.available_rewards.append(0)

                    if action == 'stay_charging' or action == 'go_charge':
                        charging = 1
                        charging_from = task_end + timedelta(minutes=5)
                        self.matched_rewards.append(0)
                    elif action == 'gather_reward':
                        charging = 0
                        discharging_from = task_end + timedelta(minutes=5)
                        self.matched_rewards.append(0)

                    self.obtained_rewards.append(0)
                    
                    battery = self.get_current_battery(battery, charging, ts, charging_from, discharging_from, action)
                    
                else:
                    obtained_rew = self.get_obtained_rew(ts, discharging_from, charging)
                    self.obtained_rewards.append(obtained_rew)                
                    
                    battery = self.get_current_battery(battery, charging, ts, charging_from, discharging_from, action)

            pmodel = self.obtain_prism_model(probt, probm, rews, battery, charging, clid)
            e_t = datetime.now()
            action = self.get_policy_action(pmodel)
            e_t = datetime.now() - e_t
            print e_t
            self.iter_tracker.append(e_t)
            self.time.append(ts)
            self.battery.append(battery)
            self.charging.append(charging)
            self.actions.append(action)
            self.available_rewards.append(current_rew)

            if action == 'stay_charging' or action == 'go_charge':
                charging = 1
                charging_from = ts
                self.matched_rewards.append(0)
            elif action == 'gather_reward':
                charging = 0
                discharging_from = ts
                self.matched_rewards.append(rews[clid])

            task_end =  current_tasks['end'].max()
            
            if e == len(unique_ts)-1:
                if bool(charging):
                    self.obtained_rewards.append(0)
                else:
                    self.obtained_rewards.append(current_tasks['priority'].sum())

            self.timing_tracker.append(self.iter_tracker)


    def get_policy_action(self, pmodel):
        init_state = pmodel.initial_state
        nx_s, trans_prob, actions = pmodel.get_possible_next_states(init_state)
        return actions[0]
    

    def obtain_prism_model(self, probt, probr, clusters, init_battery, init_charging, init_clid):      
        mf_t = datetime.now()
        pm = bcth_prism_model.PrismModel('model_tbrhc.prism', self.horizon, init_battery, init_charging, init_clid, probt, clusters, probr, self.charge_model, self.discharge_model)
        mf_t = datetime.now() - mf_t
        self.iter_tracker.append(mf_t)
        p_t = datetime.now()
        #######################SPECIFY LOCATION ######################
        # running prism and saving output from prism
        with open(self.path_data+'result_tbrhc', 'w') as file:
            process = subprocess.Popen('./prism '+ self.path_mod + 'model_tbrhc.prism '+ self.path_mod +'batterycost_model_prop.props -paretoepsilon 0.1 -v -exportadv '+ self.path_mod+ 'model_tbrhc.adv -exportprodstates ' + self.path_mod +'model_tbrhc.sta -exporttarget '+self.path_mod+'model_tbrhc.lab',cwd='/home/milan/prism/prism/bin', shell=True, stdout=subprocess.PIPE)
            for c in iter(lambda: process.stdout.read(1), ''):
                sys.stdout.write(c)
                file.write(c)
        p_t = datetime.now() - p_t
        print "prism run time:" , p_t
        self.iter_tracker.append(p_t)
        ##reading output from prism to find policy file
        ### for bcth
        pr_t = datetime.now()
        policy_file = []
        pre1_point = None
        pre2_point = None
        with open(self.path_data+'result_tbrhc', 'r') as f:
            line_list = f.readlines()
            f_no_list = []
            pareto_points = []
            init = 0
            for e, line in enumerate(line_list):
                if 'pre1.adv' in line:
                    pre1_point = abs(float(line_list[e+1].split(',')[0].split('(')[1].strip()))

                if 'pre2.adv' in line:
                    pre2_point = abs(float(line_list[e+1].split(',')[0].split('(')[1].strip())) 

                if ': New point is (' in line:
                    el = line.split(' ')
                    if init == 0:
                        init_no = int(el[0][:-1])
                    cost40 = abs(float(el[4][1:-1]))
                    pareto_points.append(cost40)
                    f_no_list.append(str(int(el[0][:-1])-2))
                    init +=1 
               
        if 'pre1' == self.req_pareto_point or 'pre2' == self.req_pareto_point:
            f_no = self.req_pareto_point
            if self.req_pareto_point == 'pre1':
                self.pareto_point.append(pre1_point)
            elif self.req_pareto_point == 'pre2':
                self.pareto_point.append(pre2_point)
        else:
            if f_no_list:
                if self.req_pareto_point > 3 and self.req_pareto_point < 6:
                    approx_p_point = min(pareto_points) + ((max(pareto_points)-min(pareto_points))/3)*(float((self.req_pareto_point%3))/3)
                elif self.req_pareto_point == 6:
                    sorted_pareto_points = sorted(pareto_points)
                    if len(sorted_pareto_points) > 1:
                        approx_p_point = sorted_pareto_points[1]
                    else:
                        approx_p_point = sorted_pareto_points[0]

                else:
                   approx_p_point = min(pareto_points) + ((max(pareto_points)-min(pareto_points)))*(float(self.req_pareto_point)/3) ## 3 -> no. of pareto points being considered
                p_point = min(pareto_points, key=lambda x: abs(x-approx_p_point))
                self.pareto_point.append(p_point)
                f_ind = pareto_points.index(p_point)
                f_no = f_no_list[f_ind]
            else:
                f_no = None 
        
        if f_no != None:
            print 'Reading from model_tbrhc'+f_no+'.adv'
            pp = bc_read_adversary.ParseAdversary(['model_tbrhc'+f_no+'.adv', 'model_tbrhc.sta', 'model_tbrhc.lab'])
            pr_t = datetime.now() - pr_t
            self.iter_tracker.append(pr_t)
            return pp
        else:
            raise ValueError('Adversary Not Found !!!')


    def get_plan(self, fname):
        if 'pre1' == self.req_pareto_point or 'pre2' == self.req_pareto_point:
            plan_path = self.path_data + self.req_pareto_point+ fname
        else:
            plan_path = self.path_data + 'p'+ str(self.req_pareto_point)+ fname
        print 'Writing plan to ', plan_path, ' ...'
        with open(plan_path, 'w') as f:
            f.write('day time battery charging action obtained_reward match_reward actual_reward pareto\n')
            for t, b, ch, a, obr, mr, ar, pp in zip(self.time, self.battery, self.charging, self.actions, self.obtained_rewards, self.matched_rewards, self.available_rewards, self.pareto_point):
                f.write('{0} {1} {2} {3} {4} {5} {6} {7}\n'.format(t, b, ch, a, obr, mr, ar, pp))

        #### for printing time tracking plan
        # with open(self.path_data+fname, 'w') as f:
        #     for it in self.timing_tracker:
        #         for e,t in enumerate(it):
        #             if e != len(it)-1:
        #                 f.write("{0}, ".format(t))
        #             else:
        #                 f.write("{0}".format(t))
        #         f.write("\n")



if __name__ == '__main__':

    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,10), datetime(2017,10,11), datetime(2017,10,12)], 0)
    tbrhc.get_plan('tbrhc_h12_101011101210_1')

    np.random.seed(1)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,10), datetime(2017,10,11), datetime(2017,10,12)], 0)
    tbrhc.get_plan('tbrhc_h12_101011101210_2')

    np.random.seed(2)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,10), datetime(2017,10,11), datetime(2017,10,12)], 0)
    tbrhc.get_plan('tbrhc_h12_101011101210_3')

    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,19), datetime(2017,10,20), datetime(2017,10,21)], 0)
    tbrhc.get_plan('tbrhc_h12_191020102110_1')

    np.random.seed(1)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,19), datetime(2017,10,20), datetime(2017,10,21)], 0)
    tbrhc.get_plan('tbrhc_h12_191020102110_2')

    np.random.seed(2)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,19), datetime(2017,10,20), datetime(2017,10,21)], 0)
    tbrhc.get_plan('tbrhc_h12_191020102110_3')

    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,29), datetime(2017,10,30), datetime(2017,10,31)], 0)
    tbrhc.get_plan('tbrhc_h12_291030103110_1')

    np.random.seed(1)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,29), datetime(2017,10,30), datetime(2017,10,31)], 0)
    tbrhc.get_plan('tbrhc_h12_291030103110_2')

    np.random.seed(2)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,10,29), datetime(2017,10,30), datetime(2017,10,31)], 0)
    tbrhc.get_plan('tbrhc_h12_291030103110_3')

    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,11,4), datetime(2017,11,5), datetime(2017,11,6)], 0)
    tbrhc.get_plan('tbrhc_h12_411511611_1')

    np.random.seed(1)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,11,4), datetime(2017,11,5), datetime(2017,11,6)], 0)
    tbrhc.get_plan('tbrhc_h12_411511611_2')

    np.random.seed(2)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,11,4), datetime(2017,11,5), datetime(2017,11,6)], 0)
    tbrhc.get_plan('tbrhc_h12_411511611_3')

    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,11,12), datetime(2017,11,13), datetime(2017,11,14)], 0)
    tbrhc.get_plan('tbrhc_h12_121113111411_1')

    np.random.seed(1)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,11,12), datetime(2017,11,13), datetime(2017,11,14)], 0)
    tbrhc.get_plan('tbrhc_h12_121113111411_2')

    np.random.seed(2)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,11,12), datetime(2017,11,13), datetime(2017,11,14)], 0)
    tbrhc.get_plan('tbrhc_h12_121113111411_3')
     
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,12,1), datetime(2017,12,2), datetime(2017,12,3)], 0)
    tbrhc.get_plan('tbrhc_h12_112212312_1')

    np.random.seed(1)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,12,1), datetime(2017,12,2), datetime(2017,12,3)], 0)
    tbrhc.get_plan('tbrhc_h12_112212312_2')

    np.random.seed(2)
    tbrhc = TaskBasedRHC(6, 70, 1, [datetime(2017,12,1), datetime(2017,12,2), datetime(2017,12,3)], 0)
    tbrhc.get_plan('tbrhc_h12_112212312_3')