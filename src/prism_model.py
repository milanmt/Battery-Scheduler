#! /usr/bin/env python

import probabilistic_rewards
import subprocess

class PrismModel:
    
    def __init__(self,filename, init_t, init_b, init_ch, clusters, prob, charge_model, discharge_model):
        # initial values that make model. from_t set to zero
        self.clusters = clusters
        self.prob = prob
        self.actions = ['gather_reward', 'go_charge', 'stay_charging']
        self.charge_model = charge_model
        self.discharge_model = discharge_model
        self.time_int = 48
        self.write_prism_file(filename, init_t, init_b, init_ch) 
        
    def write_prism_file(self, filename, init_t, init_b, init_ch):
        #######################SPECIFY LOCATION ######################       
        path = '/home/milan/workspace/strands_ws/src/battery_scheduler/models/' + filename 
        with open(path, 'w') as f:
            f.write('mdp\n\n')
            f.write('module time_model\n')
            f.write('t:[0..{0}] init {1}\n'.format(self.time_int,init_t))
            f.write('task_present:[0..1] init 0\n')
            f.write('o:[0..1] init 0\n')
            f.write("[observe] (t<{0}) & (o=0) -> 0.5:(task_present'=1) & (o'=1) + 0.5:(task_present'=0) & (o'=1);\n".format(self.time_int))
            for action in self.actions:
                f.write("[{0}] (t<{1}) & (o=1) -> (t'=t+1) & (o'=0);\n".format(action, self.time_int))
            f.write("[dead] (t<{0}) -> (t'=t+1) & (o'=0);\n".format(self.time_int))
            f.write('endmodule\n\n')

            f.write('module battery_model\n')
            f.write('battery:[0..100] init {0};\n\n'.format(init_b))
            ##### PROBABILISTIC BATTERY
            for b in self.discharge_model:
                if b != 0:
                    bnext_dict = self.discharge_model[b]
                    total = np.sum(np.array(bnext_dict.values()))
                    f.write("[gather_reward] (battery={0}) -> ".format(b))
                    plus = 0
                    for bnext, val in bnext_dict.items():
                        if plus != 0:
                            f.write(' + ')
                        f.write("{0}:(battery'={1})".format(float(val)/float(total), bnext))
                        plus = plus +1
                    f.write(';\n')

            for b in self.charge_model:
                if b != 0:
                    if b == 100:
                        bnext_dict = self.charge_model[b]
                        total = np.sum(np.array(bnext_dict.values()))
                        f.write("[go_charge] (battery={0}) -> ".format(b))
                        plus = 0
                        for bnext, val in bnext_dict.items():
                            if plus != 0:
                                f.write(' + ')
                            f.write("{0}:(battery'={1})".format(float(val)/float(total), bnext))
                            plus = plus +1
                        f.write(';\n')
                    else:
                        bnext_dict = self.charge_model[b]
                        total = np.sum(np.array(bnext_dict.values()))
                        f.write("[go_charge] (battery={0}) -> ".format(b))
                        plus = 0
                        for bnext, val in bnext_dict.items():
                            if plus != 0:
                                f.write(' + ')
                            f.write("{0}:(battery'={1})".format(float(val)/float(total), bnext-1))
                            plus = plus +1
                        f.write(';\n')

            for b in self.charge_model:
                bnext_dict = self.charge_model[b]
                total = np.sum(np.array(bnext_dict.values()))
                f.write("[stay_charging] (battery={0}) -> ".format(b))
                plus = 0
                for bnext, val in bnext_dict.items():
                    if plus != 0:
                        f.write(' + ')
                    f.write("{0}:(battery'={1})".format(float(val)/float(total), bnext))
                    plus = plus +1
                f.write(';\n')


            #### DET BATTERY
            # for b in self.discharge_model:
            #     if b != 0:
            #         bnext_dict = self.discharge_model[b]
            #         total = np.sum(np.array(bnext_dict.values()))
            #         avg = 0.0
            #         for bnext, val in bnext_dict.items():
            #             avg = avg + bnext*val
            #         f.write("[gather_reward] (battery={0}) -> 1:(battery'={1});\n".format(b, int(round(avg/total))))
            #         # if b-int(round(avg/total)) not in self.dm:
            #         #     b_list = []
            #         # else:
            #         #     b_list = self.dm[b-int(round(avg/total))]
            #         # print b-int(round(avg/total)), b
            #         # b_list.append(b)
            #         # self.dm.update({b-int(round(avg/total)) : b_list })

            # for b in self.charge_model:
            #     bnext_dict = self.charge_model[b]
            #     total = np.sum(np.array(bnext_dict.values()))
            #     avg = 0.0
            #     for bnext, val in bnext_dict.items():
            #         avg = avg + bnext*val
            #     if b!= 0:
            #         if b == 100:
            #             f.write("[go_charge] (battery={0}) -> 1:(battery'={1});\n".format(b, int(round(avg/total))))
            #         f.write("[go_charge] (battery={0}) -> 1:(battery'={1});\n".format(b, int(round(avg/total)-1)))

            #     # if int(round(avg/total))-1-b not in self.gm:
            #     #     b_list = []
            #     # else:
            #     #     b_list = self.gm[int(round(avg/total))-1-b]
            #     # print int(round(avg/total))-1-b, b
            #     # b_list.append(b)
            #     # self.gm.update({int(round(avg/total))-1-b : b_list })

            # for b in self.charge_model:
            #     bnext_dict = self.charge_model[b]
            #     total = np.sum(np.array(bnext_dict.values()))
            #     avg = 0.0
            #     for bnext, val in bnext_dict.items():
            #         avg = avg + bnext*val
            #     f.write("[stay_charging] (battery={0}) -> 1:(battery'={1});\n".format(b, int(round(avg/total))))
            #     # if int(round(avg/total))-b not in self.cm:
            #     #     b_list = []
            #     # else:
            #     #     b_list = self.cm[int(round(avg/total))-b]
            #     # print int(round(avg/total))-b, b
            #     # b_list.append(b)
            #     # self.cm.update({int(round(avg/total))-b : b_list })

            f.write("[finish] (battery=0) -> (battery' = battery);\n\n")
            f.write('endmodule\n\n\n')

            f.write('module charging_state\n\n')
            f.write('charging:[0..1] init {0};\n'.format(init_ch))
            f.write("[gather_reward] (charging=0) | (charging=1) -> (charging'=0);\n")
            f.write("[stay_charging] (charging=1) -> (charging'=1);\n")
            f.write("[go_charge] (charging=0) -> (charging'=1);\n")
            f.write("[finish] (charging=0) -> (charging'=0);\n\n")
            f.write('endmodule\n\n\n')

            f.write('module time_model\n\n')
            f.write('t:[0..{0}] init {1};\n'.format(self.time_int,init_t))
            for action in self.actions:
                f.write("[{0}] (t<{1}) -> (t'=t+1);\n".format(action,self.time_int))
            f.write("[finish] (t<{0}) -> (t'={0});\n".format(self.time_int))
            f.write('\n')
            f.write('endmodule\n\n\n')

            f.write('module cluster_evolution\n\n')
            f.write('cl:[0..{0}] init {1};\n\n'.format((self.total_cl), init_cluster))
            cl_no = 0
            for i in range(self.time_int+1): #change to 48, if 48
                if i == self.time_int:
                    for action in self.actions:
                        f.write('[{0}] (t={1}) -> '.format(action,i-1))
                        f.write("1:(cl'={0});\n".format(cl_no))

                else:
                    for action in self.actions:
                        if cl_no >= len(self.prob[0]):
                            f.write('[{0}] (t={1}) -> '.format(action,i-1))
                        for j in range(len(self.prob[i])):
                            if j == len(self.prob[i])-1 and cl_no >= len(self.prob[0]):
                                f.write("{0}:(cl'={1});\n".format(self.prob[i][j], cl_no))
                            elif cl_no >= len(self.prob[0]):
                                f.write("{0}:(cl'={1}) + ".format(self.prob[i][j], cl_no))
                            cl_no = cl_no + 1

                        if action != self.actions[-1]:
                            cl_no = cl_no - len(self.prob[i])

            f.write("[finish] true -> 1:(cl'={0});\n".format(self.total_cl))
            f.write('\n\n')
            f.write('endmodule\n\n\n')

            f.write('rewards "rew"\n\n')
            # For n clusters in total in 49 time steps
            cl_no = 0
            for i in range(self.time_int):
                for j in range(len(self.clusters[i])):
                    f.write('[gather_reward](cl={0}):{1};\n'.format(cl_no, self.clusters[i][j]))
                    cl_no = cl_no+1
            f.write('[gather_reward](cl={0}):0;\n'.format(cl_no))
            f.write('\nendrewards\n\n')
               
if __name__ == '__main__':
    ur = probabilistic_rewards.uncertain_rewards()
    prob, clusters = ur.get_probabilistic_reward_model()
    python3command = "python3 ./probabilistic_battery_model"
    charge_model, discharge_model = probabilistic_battery_model.get_battery_model('/media/milan/DATA/battery_logs')
    mm = make_model('model_test.prism', 0, 70, 1, 1, clusters, prob, charge_model, discharge_model)

    ### Just read yaml file for now