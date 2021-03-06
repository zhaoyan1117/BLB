import unittest

from blb import BLB
from asp.avro_inter.py_avro_inter import *
from Queue import PriorityQueue
import os

class SVMEmailVerifierBLB(BLB):

    TYPE_DECS = (['compute_estimate', [('array', 'CompressedFeatureVec'), ('array', ('array', 'double'))], 'double'],
         ['reduce_bootstraps', [('array', 'double')], 'double'],
         ['average', [('array', 'double')], 'double'])

    def compute_estimate(feature_vecs, models):
        errors =0.0
        num_feature_vecs = 0
        num_classes = len(models)
        for feature_vec in feature_vecs:
            weight = feature_vec.weight
            num_feature_vecs += weight
            tag = feature_vec.tag
            choice = 0
            max_match = -1.0
            for i in range(num_classes):
                model = models[i]  
                total = HelperFuncs.dot(model, feature_vec)
                if total > max_match:
                    choice = i + 1
                    max_match = total    
            if choice != tag:
                errors += weight                
        return errors / num_feature_vecs
    
    #calculates average error estimate
    def reduce_bootstraps(bootstraps):
        mean = 0.0
        for bootstrap in bootstraps:
            mean += bootstrap
        return mean / len(bootstraps)
    
    #calculates stddev on error estimates
    def reduce_bootstraps(bootstraps):
        mean = 0.0
        for bootstrap in bootstraps:
            mean += bootstrap
        mean = mean / len(bootstraps)
        squared_dif =0.0
        for bootstrap in bootstraps:           
            squared_dif += (mean-bootstrap) * (mean-bootstrap)
        return (squared_dif  / (len(bootstraps)-1)) ** .5
        
    def average(subsamples):
        mean = 0.0
        for subsample in subsamples:
            mean += subsample
        return mean/len(subsamples)

class SVMMultimediaVerifierBLB(BLB):

    TYPE_DECS = (['compute_estimate', [('array', 'FeatureVec'), ('array', ('array', ('array','float')))], ('array', 'float')],
         ['reduce_bootstraps', [('array', ('array', 'float'))], ('array','float')],
         ['average', [('array', ('array','float'))], ('array', 'float')],
         ['run', [('array', ('array','float'))], ('list','float')])

    def compute_estimate(feature_vecs, models):
        num_classes = len(models)
        file_scores = [[0.0] * len(feature_vecs)] * num_classes
        file_tags = [0] * len(feature_vecs)
        file_index = 0
        tag = 0

        #compute score for each file 
        for feature_vec in feature_vecs:
            tag = feature_vec.tag
            file_tags[file_index] = tag 
            for i in range(num_classes):
                if feature_vec.weight > 0:
                    model = models[i]
                    class_score = 0.0
                    for sub_model in model:
                        class_score  += HelperFuncs.dot(sub_model, feature_vec)
                    file_scores[i][file_index] = class_score
            file_index += 1

        #compute threshold for each class s.t. FA <= 5% for each class
        TARGET_FA_RATE = .05
        file_index = 0
        class_index = 0
        class_thresholds = [0.0] * num_classes
        num_negative = 0
        for class_scores in file_scores:
            negative_scores = [[0.0, 0.0]] * len(feature_vecs)
            file_index = 0
            negative_index = 0
            total_negative = 0.0
            for score in class_scores:
                tag = file_tags[file_index]
                if tag != class_index+1:
                    weight = float(feature_vecs[file_index].weight)
                    negative_scores[negative_index] = [score, weight]
                    negative_index += 1
                    total_negative += weight
                file_index += 1 
            
            negative_scores = negative_scores[0:negative_index]
            negative_scores.sort()
            summed = 0.0
            negative_index = 0
            neg_score_pair = [0.0, 0.0]
            while (summed/ total_negative < (1.0 -TARGET_FA_RATE)):
                neg_score_pair = negative_scores[negative_index]
                summed += neg_score_pair[1]
                negative_index +=1
            class_thresholds[class_index] = neg_score_pair[0]

            class_index += 1

        #compute MD % for each class
        md_ratios = [float(0.0)] * num_classes
        class_index = 0
        for class_scores in file_scores:
            md_total = 0
            class_occurrences = 0
            file_index = 0

            for score in class_scores:
                tag = file_tags[file_index]
                if tag == class_index+1:
                    class_occurrences += feature_vecs[file_index].weight
                    if score < class_thresholds[class_index]:
                        md_total += feature_vecs[file_index].weight
                file_index +=1
            if class_occurrences != 0:
                md_ratios[class_index] = float(md_total *1.0 / class_occurrences)
            class_index += 1

        return md_ratios

    #computes std dev
    def reduce_bootstraps(bootstraps):
        class_md_ratios = [float(0.0)] * len(bootstraps)
        std_dev_md_ratios = [float(0.0)] * len(bootstraps[0])
        for i in range(len(bootstraps[0])):
            count = 0
            for md_ratios in bootstraps:
                class_md_ratios[count] = md_ratios[i] 
                count += 1 
            std_dev_md_ratios[i] = scala_lib.std_dev(class_md_ratios)
        return std_dev_md_ratios

    def average(subsamples):
        class_std_dev_md_ratios = [float(0.0)] * len(subsamples)
        avg_std_dev_md_ratios = [float(0.0)] * len(subsamples[0])
        for i in range(len(subsamples[0])):
            count = 0
            for md_ratios in subsamples:
                class_std_dev_md_ratios[count] = md_ratios[i] 
                count += 1 
            avg_std_dev_md_ratios[i] = scala_lib.mean(class_std_dev_md_ratios)
        return avg_std_dev_md_ratios

class NGramRatiosBLB(BLB):
    TYPE_DECS = (['compute_estimate', [('array', 'NGramRow')], ('array', 'double')],
         ['reduce_bootstraps', [('array', ('array', 'double'))], ('array', 'double')],
         ['average', [('array', ('array','double'))], ('array','double')])

    def compute_estimate(btstrap_data):
        BEGINNING_DECADE = 1890
        TOTAL_DECADES = (2010-BEGINNING_DECADE)/10
        NUM_TOP_RATIOS = 10000
        MIN_FREQUENCY_THRESH = 0.000001

        #obtain total number of occurrences per decade 
        ngram_tab_split=['']
        year_split=['']
        occurrences = 0.0
        year = 0

        decade_total_occurrences  = [0.0] * TOTAL_DECADES
        decadeIndex = 0
        for ngram_row in btstrap_data:
            ngram_tab_split = ngram_row.year_counts.split("\t")
            ngram = ngram_tab_split[0]
            for year_count in ngram_tab_split[1:len(ngram_tab_split)]:
                year_split = year_count.split(' ')
                year = int(year_split[0])
                occurrences = int(year_split[1]) * ngram_row.weight
                if year >= BEGINNING_DECADE:
                    decadeIndex = int((year/ 100.0 - BEGINNING_DECADE/100.0) * 10.0)
                    decade_total_occurrences[decadeIndex] += occurrences

        #obtain word frequency ratios between decades 
        top_n_ratios_per_decade = [PriorityQueue() for i in range(TOTAL_DECADES -1)]

        decade_ratio_mins = [0.0] * (TOTAL_DECADES-1)
        ngram_decade_frequency = [0.0] * TOTAL_DECADES
        ngram_decade_occurrences = [0.0] * TOTAL_DECADES

        for ngram_row in btstrap_data:
            ngram_tab_split = ngram_row.year_counts.split("\t")
            for year_count in ngram_tab_split[1:len(ngram_tab_split)]:
                year_split = year_count.split(' ')
                year = int(year_split[0])
                occurrences = int(year_split[1]) * ngram_row.weight
                if year >= BEGINNING_DECADE:
                    decadeIndex = int((year/ 100.0 - BEGINNING_DECADE/100.0) * 10.0)
                    ngram_decade_occurrences[decadeIndex] += occurrences 

            for decadeIndex in range(1,len(decade_total_occurrences)):
                if (decade_total_occurrences[decadeIndex] > 0 and decade_total_occurrences[decadeIndex-1] > 0 and ngram_decade_occurrences[decadeIndex-1] > 0 and ngram_decade_occurrences[decadeIndex] / decade_total_occurrences[decadeIndex] > MIN_FREQUENCY_THRESH):
                    ratio = (ngram_decade_occurrences[decadeIndex] / decade_total_occurrences[decadeIndex]) / (ngram_decade_occurrences[decadeIndex-1] / decade_total_occurrences[decadeIndex-1]) 
                    
                    if ratio > decade_ratio_mins[decadeIndex-1]:
                        while top_n_ratios_per_decade[decadeIndex-1].qsize() < NUM_TOP_RATIOS and ngram_row.weight > 0:
                            PriorityQueue.put(top_n_ratios_per_decade[decadeIndex-1], ratio)

                            if (top_n_ratios_per_decade[decadeIndex-1].qsize() >= NUM_TOP_RATIOS):
                                PriorityQueue.get(top_n_ratios_per_decade[decadeIndex-1])
                            lowest_ratio = PriorityQueue.get(top_n_ratios_per_decade[decadeIndex-1])
                            decade_ratio_mins[decadeIndex-1] = lowest_ratio
                            PriorityQueue.put(top_n_ratios_per_decade[decadeIndex-1], lowest_ratio)
                            ngram_row.weight -= 1

            ngram_decade_occurrences = [0.0] * TOTAL_DECADES
    
        decade_ratios_arr = [0.0] * (TOTAL_DECADES-1)
        count = 0
        for queue in top_n_ratios_per_decade:
            ratios_summed = 0.0
            for i in range(NUM_TOP_RATIOS): 
                if top_n_ratios_per_decade[count].qsize() > 0:
                    ratios_summed += PriorityQueue.get(top_n_ratios_per_decade[count])

            decade_ratios_arr[count] = ratios_summed / NUM_TOP_RATIOS
            count += 1
        return decade_ratios_arr

    # def reduce_bootstraps(bootstraps):
    #     decade_ratios = [0.0] * len(bootstraps)
    #     std_dev_ratios = [0.0] * len(bootstraps[0])
    #     for i in range(len(bootstraps[0])):
    #         count = 0
    #         for cross_decades in bootstraps:
    #             decade_ratios[count] = cross_decades[i] 
    #             count += 1 
    #         std_dev_ratios[i] = scala_lib.std_dev(decade_ratios)
    #     return std_dev_ratios

    def reduce_bootstraps(subsamples):
        decade_std_devs = [0.0] * len(subsamples)
        avg_std_dev_ratios = [0.0] * len(subsamples[0])
        for i in range(len(subsamples[0])):
            count = 0
            for cross_decades in subsamples:
                decade_std_devs[count] = cross_decades[i] 
                count += 1 
            avg_std_dev_ratios[i] = scala_lib.mean(decade_std_devs)
        return avg_std_dev_ratios     

    def average(subsamples):
        decade_std_devs = [0.0] * len(subsamples)
        avg_std_dev_ratios = [0.0] * len(subsamples[0])
        for i in range(len(subsamples[0])):
            count = 0
            for cross_decades in subsamples:
                decade_std_devs[count] = cross_decades[i] 
                count += 1 
            avg_std_dev_ratios[i] = scala_lib.mean(decade_std_devs)
        return avg_std_dev_ratios     

class SVMVerifierBLBTest(unittest.TestCase):
    def test_feature_vec_classifier(self): 
        test_blb = SVMEmailVerifierBLB(25, 50, .7, with_scala=True)    
        result = test_blb.run(os.environ['HDFS_URL'] +'/test_examples/data/100xemails.dat',\
                              '/mnt/test_examples/models/emails.model.java')
        print 'FINAL RESULT IS:', result  

    def test_multimedia_classifier(self): 
        test_blb = SVMMultimediaVerifierBLB(25, 50, .85, with_scala=True)    
        result = test_blb.run(os.environ['HDFS_URL']+'/test_examples/data/40percente1-15.dat',\
                              '/mnt/test_examples/models/e1-15float.model.java')
        print 'FINAL RESULT IS:', result  

    def test_ngram_ratio_calculator(self):
        test_blb = NGramRatiosBLB(25, 50, .7, with_scala=True)
        result = test_blb.run(os.environ['HDFS_URL']+'/test_examples/data/10_percent_cleaned_blb.seq')
        print 'FINAL RESULT IS:', result  

if __name__ == '__main__':
    spark_test_suite = unittest.TestSuite()
    #spark_test_suite.addTest(SVMVerifierBLBTest('test_feature_vec_classifier'))
    spark_test_suite.addTest(SVMVerifierBLBTest('test_multimedia_classifier'))
    #spark_test_suite.addTest(SVMVerifierBLBTest('test_ngram_ratio_calculator'))
    unittest.TextTestRunner().run(spark_test_suite)

