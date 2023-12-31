import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from torch.autograd import Variable
from tqdm import tqdm 
import sys
import numpy as np
from utils.loss import CMD
from sklearn.preprocessing import OneHotEncoder
from sklearn.preprocessing import LabelEncoder
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def student_train(t_encoder,temporal_c,temporal_v,spatial_c,spatial_v,cross_att,t_classifier,s_encoder,s_classifier,discriminator1,discriminator2, optimizer, source_dataloader1,source_dataloader2,target_dataloader,epoch):
    step=0
    gamma = 10

    items=np.array(["s1", "t"]).reshape(-1,1)
    label_encoder = LabelEncoder()
    label_encoder.fit(items)
    
    
    
    t_encoder=t_encoder.to(device)
    temporal_c=temporal_c.to(device)
    temporal_v=temporal_v.to(device)
    spatial_c=spatial_c.to(device)
    spatial_v=spatial_v.to(device)
    cross_att=cross_att.to(device)
    t_classifier=t_classifier.to(device)
    
    s_encoder=s_encoder.to(device)
    s_classifier=s_classifier.to(device)
    discriminator1=discriminator1.to(device)
    discriminator2=discriminator2.to(device)

    best_score = 0
    best_s_encoder = None
    best_s_classifier = None
    best_discirminator1=None
    best_discirminator2=None
    domain_criterion = nn.CrossEntropyLoss().to(device)

    criterion = nn.CrossEntropyLoss().to(device)
    kldiv = nn.KLDivLoss().to(device)
    best_score = 0
    t_encoder.eval()
    temporal_c.eval()
    temporal_v.eval()
    spatial_c.eval()
    spatial_v.eval()
    cross_att.eval()
    t_classifier.eval()
    
    s_encoder.train()
    s_classifier.train()
    discriminator1.train()
    discriminator2.train()
    # steps
    start_steps = epoch * len(source_dataloader1)
    total_steps = 10 * len(source_dataloader1)
    mincmd=999999999999
    for batch_idx, (sdata1, sdata2, tdata) in enumerate(zip(source_dataloader1, source_dataloader2, target_dataloader)):
        v_t1,v_f1,c_t1,c_f1,y1=sdata1
        v_t2,v_f2,c_t2,c_f2,y2=sdata2
        v_t3,v_f3,c_t3,c_f3,y3=tdata
        
        
        # setup hyperparameters
        p = float(batch_idx + start_steps) / total_steps
        constant = 2. / (1. + np.exp(-gamma * p)) - 1
        
        optimizer.zero_grad()
            
        #teacher1
        t_v_r1,t_c_r1,t_v_f1,t_c_f1= t_encoder(v_t1,v_f1,c_t1,c_f1)
        t_c_r1=temporal_c(t_c_r1)
        t_v_r1=temporal_v(t_v_r1)
        t_c_f1=spatial_c(t_c_f1)
        t_v_f1=spatial_v(t_v_f1)
        att_c1,att_v1=torch.cat([t_c_r1,t_c_f1], dim=1),torch.cat([t_v_r1,t_v_f1], dim=1)
        att1=cross_att(att_c1,att_v1)
        out1, logits21,feature1= t_classifier(att1)
        #teacher2
        t_v_r2,t_c_r2,t_v_f2,t_c_f2= t_encoder(v_t2,v_f2,c_t2,c_f2)
        t_c_r2=temporal_c(t_c_r2)
        t_v_r2=temporal_v(t_v_r2)
        t_c_f2=spatial_c(t_c_f2)
        t_v_f2=spatial_v(t_v_f2)
        att_c2,att_v2=torch.cat([t_c_r2,t_c_f2], dim=1),torch.cat([t_v_r2,t_v_f2], dim=1)
        att2=cross_att(att_c2,att_v2)
        out2, logits22,feature2= t_classifier(att2)
        
            
        #student1
     
        raw_f1,fft_f1,s_feature11= s_encoder(c_t1,c_f1)
        
        # loss1
        time_distill_loss1 = kldiv(nn.functional.log_softmax(t_c_r1, dim=1),nn.functional.softmax(raw_f1, dim=1))
        spectral_distill_loss1 = kldiv(nn.functional.log_softmax(t_c_f1, dim=1),nn.functional.softmax(fft_f1, dim=1))
        cross_att_distill_loss1 = kldiv(nn.functional.log_softmax(att1, dim=1),nn.functional.softmax(s_feature11, dim=1))

        s_out1, s_logits21, s_feature21,dfeature1= s_classifier(s_feature11)
        
        end_feature_distill_loss1 = kldiv(nn.functional.log_softmax(logits21, dim=1),nn.functional.softmax(s_logits21, dim=1))
        
        kd_loss1=time_distill_loss1+spectral_distill_loss1+cross_att_distill_loss1+end_feature_distill_loss1
        class_loss1 = criterion(s_out1, y1)
        
        # print("y1",y1)
        # print("s_out1",s_out1)
        #student
        raw_f2,fft_f2,s_feature12= s_encoder(c_t2,c_f2)
        # loss2
        time_distill_loss2 = kldiv(nn.functional.log_softmax(t_c_r2, dim=1),nn.functional.softmax(raw_f2, dim=1))
        spectral_distill_loss2 = kldiv(nn.functional.log_softmax(t_c_f2, dim=1),nn.functional.softmax(fft_f2, dim=1))
        cross_att_distill_loss2 = kldiv(nn.functional.log_softmax(att2, dim=1),nn.functional.softmax(s_feature12, dim=1))

        s_out2, s_logits22, s_feature22,dfeature2= s_classifier(s_feature12)
        end_feature_distill_loss2 = kldiv(nn.functional.log_softmax(logits22, dim=1),nn.functional.softmax(s_logits22, dim=1))
        
        kd_loss2=time_distill_loss2+spectral_distill_loss2+cross_att_distill_loss2+end_feature_distill_loss2
        class_loss2 = criterion(s_out2, y2)
        
        
        source_labels1 = Variable(torch.tensor(label_encoder.transform((np.array(["s1"]*32).reshape(-1,1)))).type(torch.long).to(device))
        source_labels2 = Variable(torch.tensor(label_encoder.transform((np.array(["s1"]*32).reshape(-1,1)))).type(torch.long).to(device))
        target_labels = Variable(torch.tensor(label_encoder.transform((np.array(["s1"]*32).reshape(-1,1)))).type(torch.long).to(device))            # compute the domain loss of src_feature and target_feature

        #target data
        raw_f3,fft_f3,s_feature13= s_encoder(c_t3,c_f3)
        s_out3, s_logits23, s_feature23,dfeature3= s_classifier(s_feature13)

        #domain discriminator
        _,d1=discriminator1(dfeature1, constant)
        _,d2=discriminator2(dfeature2, constant)
        _,d3=discriminator1(dfeature3, constant)
        _,d4=discriminator2(dfeature3, constant)
        tgt_loss1 = domain_criterion(d3, target_labels)
        tgt_loss2 = domain_criterion(d4, target_labels)
        src_loss1 = domain_criterion(d1, source_labels1)
        src_loss2 = domain_criterion(d2, source_labels2)
        
        #weight
        if epoch<10:
            w1,w2=0.5,0.5
            cmd_val=999999999999
        else:
            cmd1=CMD(s_feature13, s_feature11)
            cmd2=CMD(s_feature13, s_feature12)

            
            cmd_val=cmd1+cmd2
            if cmd_val<mincmd:
                mincmd=cmd_val
            w1=cmd2/(cmd1+cmd2)
            w2=cmd1/(cmd1+cmd2)
            # print("cmd1: ",cmd1)
            # print("cmd2: ",cmd2)
            # print("weight1 and 2: ",w1,w2)
        
        
        
        
        
        class_loss= w1*class_loss1+w2*class_loss2
        kd_loss=w1*kd_loss1+w2*kd_loss2
        domain_loss =  w1*src_loss1 + w2*src_loss2
        target_domain_loss=w1*tgt_loss1+w2*tgt_loss2
        # print("class, kd, domain,target: ",class_loss,kd_loss,domain_loss,target_domain_loss)
        total_loss=class_loss+kd_loss+domain_loss+target_domain_loss
        total_loss.backward()
        optimizer.step()
    if epoch>10:
        print("cmd1: ",cmd1)
        print("cmd2: ",cmd2)
        print("weight1 and 2: ",w1,w2)
    print("class loss: ",class_loss, "kd loss: ",kd_loss, "domain loss: ",domain_loss,"target loss: ",target_domain_loss)
    print("total_loss: ",total_loss)

    return s_encoder,s_classifier,discriminator1,discriminator2, mincmd, w1,w2
    