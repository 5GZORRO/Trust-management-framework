import json
import sys
import logging
from flask import Flask, request
from flask_restful import Resource, Api
from gevent.pywsgi import WSGIServer
import random
import time
import requests
import ast
import re
from pymongo import MongoClient
import pprint
import csv
import threading
from threading import Lock
from dotenv import load_dotenv
from peerTrust import *
from producer import *
from consumer import *
from trustInformationTemplate import *
from fuzzy_sets import *
from datetime import datetime
from multiprocessing import Process, Value, Manager
#logging.basicConfig(filename='TRMF_logs',filemode='a',format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',datefmt='%H:%M:%S',level=logging.INFO)

from gevent import monkey
monkey.patch_all()

app = Flask(__name__)
api = Api(app)

producer = None
consumer = Consumer()
peerTrust = PeerTrust()
data_lock = Lock()
trustInformationTemplate = TrustInformationTemplate()

client = MongoClient(host='mongodb-trmf', port=27017, username='5gzorro', password='password')
db = client.rptutorials
mongoDB = db.tutorial

provider_list = []
considered_offer_list = []
consumer_instance = None

history = {}
trustor_acquired = False
trustorDID = ""
update_catalog = False
thread_catalog = False
newSLAViolation = False
timestamp_thread_catalog = 0
TIME_TO_UPDATE_CATALOG_INFO = 600


gather_time = 0
compute_time = 0
storage_time = 0
update_time = 0
satisfaction = 0
credibility = 0
TF = 0
CF = 0
offer_type = {}
product_offering = []
old_product_offering = []
statistic_catalog = []
threads_security = list()
threads_sla = list()

""" Parameters to define a minimum interactions in the system and avoid a cold start"""
max_previous_providers = 4
max_previous_providers_interactions = 3
max_previous_interactions = max_previous_providers * max_previous_providers_interactions


def find_by_column(column, value):
    """ This method discovers interactions registered in the Kafka looking at one specific value"""
    list = []
    for interaction in peerTrust.kafka_interaction_list:
        if interaction[column] == value:
            list.append(interaction)
    return list

class initialise_offer_type(Resource):
    """ This class recaps the type of offers being analysed per request. Then, the informatation is leveraged by the
    Computation and Update classes"""

    def post(self):
        global offer_type
        req = request.data.decode("utf-8")
        offer_type = json.loads(req)
        return 200


class start_data_collection(Resource):
    """ This method is responsible for creating the minimum information in the 5G-TRMF framework
    to avoid the cold start """

    def post(self):
        global trustor_acquired
        global gather_time
        global compute_time
        global storage_time
        global update_time
        global satisfaction
        global credibility
        global TF
        global CF
        global considered_offer_list
        global update_catalog
        global thread_catalog
        global timestamp_thread_catalog
        global producer

        gather_time, compute_time, storage_time, update_time, satisfaction, credibility, TF, CF = 0, 0, 0, 0, 0, 0, 0, 0
        trustor_acquired = False
        max_trust_score = 0
        max_trust_score_offerDID = ""
        producer = Producer()

        time_file_name = 'tests/time.csv'
        time_headers = ["start_timestamp","end_timestamp","total_time", "total_without_cold", "cold_time", "gather_time", "compute_time",
                   "storage_time", "update_time","satisfaction","credibility","TF", "CF", "offers"]

        req = request.data.decode("utf-8")
        dict_product_offers = json.loads(req)
        initial_timestamp = time.time()

        trust_scores = []
        list_product_offers = {}
        considered_offer_list = []
        kafka_minimum_interaction_list = []

        """ Loading Catalog information and launching thread to update info after 10 minutes"""
        if not update_catalog:
            self.gatherin_POs_catalog(False)
            update_catalog = True
            timestamp_thread_catalog = int(str(time.time()).split(".")[0])
        else:
            if not thread_catalog and int(str(time.time()).split(".")[0]) - timestamp_thread_catalog >= TIME_TO_UPDATE_CATALOG_INFO:
                x = threading.Thread(target=self.gatherin_POs_catalog, args=(True,))
                x.start()
                thread_catalog = True
                timestamp_thread_catalog = int(str(time.time()).split(".")[0])
            elif thread_catalog and int(str(time.time()).split(".")[0]) - timestamp_thread_catalog >= TIME_TO_UPDATE_CATALOG_INFO:
                x = threading.Thread(target=self.gatherin_POs_catalog, args=(True,))
                x.start()
                timestamp_thread_catalog = int(str(time.time()).split(".")[0])


        """ If it is not the first time that the 5G-TRMF is executed, it should retrieve information from the MongoDB
        in case of such an information is not already loaded in the historical parameter """

        for trustee in dict_product_offers:
            if trustor_acquired == False:
                trustorDID = dict_product_offers[trustee]
                list_product_offers['trustorDID'] = trustorDID
                trustor_acquired = True

            else:
                for offer in dict_product_offers[trustee]:
                    considered_offer_list.append({'trusteeDID': trustee, 'offerDID': offer})

                    """ In case of first time the 5G-TRMF is executed, we should retrieve information from MongoDB and
                    check if it is already or not in the historical"""
                    previous_interaction = mongoDB.find({'trustee.offerDID': offer})
                    offer_found = False
                    if previous_interaction is not None:
                        for interaction in previous_interaction:
                            del interaction['_id']
                            if interaction['trustor']['trusteeDID'] == trustee and \
                                    interaction['trustor']['offerDID'] == offer:
                                if interaction not in peerTrust.historical:
                                    peerTrust.historical.append(interaction)
                                offer_found = True

                    if not offer_found:
                        if trustee in list_product_offers:
                            list_product_offers[trustee].append(offer)
                        else:
                            list_product_offers[trustee] = [offer]

        consumer.start("TRMF-interconnections")
        consumer.subscribe("TRMF-interconnections")
        kafka_minimum_interaction_list = consumer.start_reading_minimum_interactions()

        if len(list_product_offers) >= 1 and bool(kafka_minimum_interaction_list):
            peerTrust.kafka_interaction_list = kafka_minimum_interaction_list

        #Uncomment following lines if we need to generate basis information to run the 5G-TRMF
        #consumer.start("TRMF-interconnections")
        #consumer.subscribe("TRMF-interconnections")
        #cold_start_info = consumer.start_reading_cold_start(max_previous_interactions)

        """ Adding a set of minimum interactions between entities that compose the trust model """
        #if len(list_product_offers)>1 and not bool(cold_start_info):
            #minimum_data = peerTrust.minimumTrustValues(producer, consumer, trustorDID, list_product_offers)

            #for data in minimum_data:
                #producer.createTopic("TRMF-interconnections")
                #producer.sendMessage("TRMF-interconnections", trustorDID, data)

            #producer.createTopic("TRMF-historical")
            #producer.sendMessage("TRMF-historical", trustorDID, peerTrust.historical)

        #elif len(list_product_offers) >= 1 and bool(cold_start_info):
            #"If we don't have the minimum stakeholder interactions we load from Kafka"
            #if not bool(peerTrust.historical):
                #consumer.start("TRMF-historical")
                #consumer.subscribe("TRMF-historical")
                #historical = consumer.start_reading_minimum_historical()

                #peerTrust.kafka_interaction_list = kafka_minimum_interaction_list
                #print("Kafka Cargado: ", peerTrust.kafka_interaction_list)
                #for i in historical:
                    #if i not in peerTrust.historical:
                        #peerTrust.historical.append(i)

            #"Adding a set of minimum interaction between entities but generated by other TRMF"
            #backup = []

            #for trustee in cold_start_info:
                #backup.append(cold_start_info[trustee])

                #if trustee not in peerTrust.list_additional_did_providers:
                    #peerTrust.list_additional_did_providers.append(trustee)
            #"If we don't have the minimum stakeholder interactions we load from Kafka"
            #if not all(elem in peerTrust.kafka_interaction_list for elem in kafka_minimum_interaction_list):
                #peerTrust.kafka_interaction_list = kafka_minimum_interaction_list
                #print("Kafka Cargado: ", peerTrust.kafka_interaction_list)

            #peerTrust.list_additional_did_offers = backup

        trustor_acquired = False

        for trustee in dict_product_offers:
            if trustor_acquired == False:
                trustor_acquired = True

            else:
                for offer in dict_product_offers[trustee]:

                    if trustee+"$"+offer not in provider_list:
                        provider_list.append(trustee+"$"+offer)

                    """ we generated initial trust information to avoid the cold start"""
                    print("$$$$$$$$$$$$$$ Starting cold start procces on ",trustee, " $$$$$$$$$$$$$$\n")
                    for key, value in list_product_offers.items():
                        if offer in value:
                            peerTrust.generateHistoryTrustInformation(producer, consumer, trustorDID, trustee, offer, 3)
                            """ Establish two new interactions per each provider"""
                            #peerTrust.setTrusteeInteractions(producer, consumer, trustee, 2)

                    print("\n$$$$$$$$$$$$$$ Ending cold start procces on ",trustee, " $$$$$$$$$$$$$$\n")

                    """ Retrieve information from trustor and trustee """
                    data = {"trustorDID": trustorDID, "trusteeDID": trustee, "offerDID": offer, "topicName": trustorDID}

                    response = requests.post("http://localhost:5002/gather_information", data=json.dumps(data).encode("utf-8"))
                    response = json.loads(response.text)

                    if response["trust_value"] > max_trust_score:
                        max_trust_score = response["trust_value"]
                        max_trust_score_offerDID = response["trusteeDID"]["offerDID"]
                    trust_scores.append(response)

        "We are currently registering as a new interaction the offer with the highest trust score"
        for interaction in reversed(peerTrust.historical):
            if interaction["trust_value"] == max_trust_score and \
                    interaction["trustor"]["offerDID"] == max_trust_score_offerDID:

                " Modifying the interaction number as the most recent one "
                interaction["currentInteractionNumber"] = peerTrust.getCurrentInteractionNumber(trustorDID)
                interaction["trustor"]["direct_parameters"]["totalInteractionNumber"] = \
                    peerTrust.getLastTotalInteractionNumber(interaction["trustor"]["trusteeDID"])

                load_dotenv()
                trmf_endpoint = os.getenv('TRMF_5GBARCELONA')
                message = {"trustorDID": trustorDID, "trusteeDID": interaction["trustor"]["trusteeDID"], "offerDID": max_trust_score_offerDID,
                        "interactionNumber": interaction["trustor"]["direct_parameters"]["interactionNumber"],
                        "totalInteractionNumber": interaction["trustor"]["direct_parameters"]["totalInteractionNumber"],
                        "currentInteractionNumber": interaction["currentInteractionNumber"], "timestamp": interaction["endEvaluationPeriod"],
                           "endpoint":trmf_endpoint}

                producer.createTopic("TRMF-interconnections")
                producer.sendMessage("TRMF-interconnections",max_trust_score_offerDID, message)

                "Adjusting the parameters based on new interactions"
                peerTrust.historical.append(interaction)

        if not os.path.exists("tests"):
            os.makedirs("tests")

        "Time measurements of the different phases to perform internal tests"
        if not os.path.exists(time_file_name):
            with open(time_file_name, 'w', encoding='UTF8', newline='') as time_data:
                writer = csv.DictWriter(time_data, fieldnames=time_headers)
                writer.writeheader()
                data = {"start_timestamp": initial_timestamp,"end_timestamp": time.time(), "total_time": time.time()-initial_timestamp,
                                "total_without_cold": gather_time+compute_time+storage_time+update_time,"cold_time":
                                    time.time()-initial_timestamp-gather_time-compute_time-storage_time-update_time,
                                "gather_time": gather_time, "compute_time": compute_time, "storage_time": storage_time,
                                "update_time": update_time, "satisfaction": satisfaction, "credibility": credibility,
                                "TF": TF, "CF": CF, "offers": 1000}
                writer.writerow(data)
        else:
            with open(time_file_name, 'a', encoding='UTF8', newline='') as time_data:
                writer = csv.DictWriter(time_data, fieldnames=time_headers)
                data = {"start_timestamp": initial_timestamp,"end_timestamp": time.time(), "total_time": time.time()-initial_timestamp,
                                "total_without_cold": gather_time+compute_time+storage_time+update_time,"cold_time":
                                    time.time()-initial_timestamp-gather_time-compute_time-storage_time-update_time,
                                "gather_time": gather_time, "compute_time": compute_time, "storage_time": storage_time,
                                "update_time": update_time, "satisfaction": satisfaction, "credibility": credibility,
                                "TF": TF, "CF": CF, "offers": 1000}
                writer.writerow(data)

        return json.dumps(trust_scores)

    def gatherin_POs_catalog(self, update_statistic):
        global statistic_catalog
        global old_product_offering

        if not bool(statistic_catalog) or update_statistic:
            """Requesting all product offering objects"""
            "5GBarcelona"
            load_dotenv()
            barcelona_address = os.getenv('5GBARCELONA_CATALOG_A')
            response = requests.get(barcelona_address+"productCatalogManagement/v4/productOffering")

            "5TONIC"
            #madrid_address = os.getenv('5TONIC_CATALOG_A')
            #response = requests.get(madrid_address+"productCatalogManagement/v4/productOffering")

            product_offering = json.loads(response.text)

            if bool(product_offering) and product_offering != old_product_offering:
                "If there is any change in the Catalog, we need to update all statistics"
                statistic_catalog = []

                for i in product_offering:
                    "Delete once the HTTP request will not be filtered in 5GBarcelona"
                    if product_offering.index(i) < 111450:
                        "Added to avoid some malformed POs"
                        if "href" in i['productSpecification'] and "172.28.3.100" not in i['productSpecification']['href']:
                            href = i['productSpecification']['href']
                            id_product_offering = i['id']
                            "Added to avoid some malformed POs"
                            if len(i['place']) > 0:
                                product_offering_location = i['place'][0]['href']
                            category = i['category'][0]['name']

                            """ Obtaining the real product offer specification object"""
                            response = requests.get(href)
                            response = json.loads(response.text)
                            if 'relatedParty' in response:
                                did_provider = response['relatedParty'][0]['extendedInfo']
                            else:
                                did_provider = ''

                            """ Obtaining the location of the product offering object"""
                            response = requests.get(product_offering_location)
                            response = json.loads(response.text)

                            "Check whether the POs have location information"
                            new_object = {}
                            location = ""

                            if "city" and "country" and "locality" in response:
                                city = response['city']
                                country = response['country']
                                locality = response['locality']
                                x_coordinate = response['geographicLocation']['geometry'][0]['x']
                                y_coordinate = response['geographicLocation']['geometry'][0]['y']
                                z_coordinate = response['geographicLocation']['geometry'][0]['z']
                                location = str(x_coordinate)+"_"+str(y_coordinate)+"_"+str(z_coordinate)

                                "Initialise the object"
                                new_object["provider"] = did_provider
                                new_object["n_resource"] = 1
                                new_object[location] = 1
                                new_object["active"] = 0
                                new_object["active"+"_"+location] = 0
                                new_object["active"+"_"+category.lower()] = 0
                                new_object["active"+"_"+category.lower()+"_"+location] = 0

                                if i['lifecycleStatus'] == 'Active':
                                    new_object["active"] = 1
                                    new_object["active"+"_"+location] = 1
                                    new_object["active"+"_"+category.lower()] = 1
                                    new_object["active"+"_"+category.lower()+"_"+location] = 1


                            if not bool(statistic_catalog) and bool(new_object):
                                statistic_catalog.append(new_object)
                            elif bool(new_object):
                                "This variable will check whether we have a new provider in the Catalog"
                                new_provider = True

                                for product_offer in statistic_catalog:
                                    if product_offer["provider"] == did_provider:
                                        new_provider = False

                                        product_offer["n_resource"] = product_offer["n_resource"] + new_object["n_resource"]
                                        if location not in product_offer:
                                            product_offer[location] = new_object[location]
                                        else:
                                            product_offer[location] = product_offer[location] + new_object[location]

                                        product_offer['active'] =  product_offer['active'] + new_object["active"]

                                        if 'active'+"_"+location not in product_offer:
                                            product_offer['active'+"_"+location] = new_object["active"+"_"+location]
                                        else:
                                            product_offer["active"+"_"+location] = product_offer["active"+"_"+location] + new_object["active"+"_"+location]

                                        if "active"+"_"+category.lower() not in product_offer:
                                            product_offer['active'+"_"+category.lower()] = new_object["active"+"_"+category.lower()]
                                        else:
                                            product_offer["active"+"_"+category.lower()] = product_offer["active"+"_"+category.lower()] + new_object["active"+"_"+category.lower()]

                                        if "active"+"_"+category.lower()+"_"+location not in product_offer:
                                            product_offer['active'+"_"+category.lower()+"_"+location] = new_object["active"+"_"+category.lower()+"_"+location]
                                        else:
                                            product_offer["active"+"_"+category.lower()+"_"+location] = product_offer["active"+"_"+category.lower()+"_"+location] + new_object["active"+"_"+category.lower()+"_"+location]

                                "Only when the provider is new, we add a new object"
                                if new_provider:
                                    statistic_catalog.append(new_object)

                old_product_offering = product_offering


class gather_information(Resource):
    def post(self):
        """ This method will retrieve information from the historical (MongoDB)+
        search for supplier/offer interactions in the Kafka bus to retrieve recommendations from
        other 5G-TRMFs. Currently there is no interaction with other 5G-TRMFs, we generate our
        internal information """

        global gather_time

        """ Retrieve parameters from post request"""
        req = request.data.decode("utf-8")
        parameter = json.loads(req)


        trustorDID = parameter["trustorDID"]
        trusteeDID = parameter["trusteeDID"]
        offerDID = parameter["offerDID"]
        topic_name = parameter["topicName"]

        print("$$$$$$$$$$$$$$ Starting data collection procces on ",trusteeDID, " $$$$$$$$$$$$$$\n")

        start_time = time.time()

        """Read last value registered in the historical"""
        last_trust_value = consumer.readLastTrustValueOffer(peerTrust.historical, trustorDID, trusteeDID, offerDID)

        print("\nThe latest trust interaction (history) of "+trustorDID+" with "+trusteeDID+" was:\n",last_trust_value, "\n")

        """Read interactions related to a Trustee"""
        interactions = self.getInteractionTrustee(trustorDID, trusteeDID)

        print("Public information from "+trusteeDID+" interactions registered in the Kafka:\n", interactions, "\n")

        print("$$$$$$$$$$$$$$ Ending data collection procces on ",trusteeDID, " $$$$$$$$$$$$$$\n")

        gather_time = gather_time + (time.time()-start_time)
        ###print("Gather time: ", gather_time)

        """ Retrieve information from trustor and trustee """
        trust_information = []
        current_offer = {"trustorDID": trustorDID, "trusteeDID": trusteeDID, "offerDID": offerDID, "topicName": topic_name, "lastValue": last_trust_value, "trusteeInteractions": interactions}
        trust_information.append(current_offer)

        response = requests.post("http://localhost:5002/compute_trust_level", data=json.dumps(trust_information).encode("utf-8"))

        response = json.loads(response.text)


        return response

    def getInteractionTrustee(self, trustorDID, trusteeDID):
        """ This method retrieves all interactions related to a Trustee"""

        return find_by_column("trustorDID", trusteeDID)

class compute_trust_level(Resource):
    def post(self):
        """This method retrieves the last value of the Trustor for a particular Trustee and the Trustee's interactions.
        It will then do the summation from its last computed value to the recent one by updating it trust value over
        the trustee """

        global compute_time
        global satisfaction
        global credibility
        global TF
        global CF
        global offer_type
        global considered_offer_list
        global availableAssets
        global totalAssets
        global availableAssetLocation
        global totalAssetLocation
        global consideredOffers
        global totalOffers
        global consideredOfferLocation
        global totalOfferLocation
        global statistic_catalog

        FORGETTING_FACTOR = 0.2

        """ Retrieve parameters from post request"""
        req = request.data.decode("utf-8")
        parameter = json.loads(req)

        for i in parameter:

            print("$$$$$$$$$$$$$$ Starting trust computation procces on ",i['trusteeDID'], " $$$$$$$$$$$$$$\n")

            start_time = time.time()

            current_trustee = i['trusteeDID']
            trustorDID = i['trustorDID']
            offerDID = i['offerDID']

            """ Recovering the last trust information """
            last_trustee_interaction_registered = i['lastValue']['totalInteractionNumber']
            last_satisfaction = i['lastValue']['trusteeSatisfaction']
            last_credibility = i['lastValue']['credibility']
            last_transaction_factor = i['lastValue']['transactionFactor']
            last_community_factor = i['lastValue']['communityFactor']
            last_interaction_number = i['lastValue']['interaction_number']
            last_trust_value = i['lastValue']['trust_value']
            last_trustor_satisfaction = i['lastValue']['userSatisfaction']

            response = {"trustorDID": trustorDID, "trusteeDID": {"trusteeDID": current_trustee, "offerDID": offerDID}, "trust_value": i['lastValue']["trust_value"], "evaluation_criteria": "Inter-domain", "initEvaluationPeriod": i['lastValue']["initEvaluationPeriod"],"endEvaluationPeriod": i['lastValue']["endEvaluationPeriod"]}

            """ Retrieving new trustee's interactions """
            print("Checking if "+current_trustee+" has had new interactions from last time we interacted with it\n")
            print("The last time "+trustorDID+" interacted with "+current_trustee+", it had had "+str(last_trustee_interaction_registered)+" interactions in total\n")

            current_trustee_interactions = i['trusteeInteractions']

            new_satisfaction = 0.0
            new_credibility = 0.0
            new_transaction_factor = 0.0
            new_community_factor = 0.0
            counter_new_interactions = 0
            counter_new_CF_interactions = 0

            """Obtaining the last interaction registered by the Trustee in the Kafka """

            if len(current_trustee_interactions) > 0:
                last_interaction_Kafka = current_trustee_interactions[len(current_trustee_interactions)-1]
                print("Currently, "+current_trustee+" has "+str(last_interaction_Kafka['currentInteractionNumber'])+" interactions in total\n")
                if int(last_interaction_Kafka['currentInteractionNumber']) > last_trustee_interaction_registered:
                    print(int(last_interaction_Kafka['currentInteractionNumber'])-last_trustee_interaction_registered, " new interactions should be contemplated to compute the new trust score on "+current_trustee+"\n")
                    print("%%%%%%%%%%%%%% Principal PeerTrust equation %%%%%%%%%%%%%%\n")
                    print("\tT(u) = α * ((∑ S(u,i) * Cr(p(u,i) * TF(u,i)) / I(u)) + β * CF(u)\n")

                    for new_interaction in current_trustee_interactions:

                        new_trustee_interaction = consumer.readLastTrustValues(peerTrust.historical, current_trustee, new_interaction['trusteeDID'], last_trustee_interaction_registered, new_interaction['currentInteractionNumber'])

                        if not bool(new_trustee_interaction):
                            new_interaction["last_trustee_interaction_registered"] = last_trustee_interaction_registered
                            endpoint = new_interaction["endpoint"].split("/")[2]
                            response = requests.post("http://"+endpoint+"/query_trust_info", data=json.dumps(new_interaction).encode("utf-8"))
                            if response.status_code == 200:
                                response = json.loads(response.text)
                            else:
                                print("Error:", response)

                            for interaction in response:
                                if bool(interaction):
                                    peerTrust.historical.append(interaction)


                        for i in new_trustee_interaction:
                            print(new_interaction['trustorDID']," had an interaction with ", new_interaction['trusteeDID'],"\n")
                            print("\tS(u,i) ---> ", i["trustee"]["trusteeSatisfaction"])
                            new_satisfaction = new_satisfaction + i["trustee"]["trusteeSatisfaction"]
                            start_credibility = time.time()
                            current_credibility = peerTrust.credibility(current_trustee, new_interaction['trusteeDID'])
                            print("\tCr(p(u,i)) ---> ", round(current_credibility, 4))
                            new_credibility = new_credibility + current_credibility
                            credibility = credibility + (time.time()-start_credibility)
                            start_TF = time.time()
                            current_transaction_factor = peerTrust.transactionContextFactor(current_trustee, new_interaction['trusteeDID'], new_interaction['offerDID'])
                            print("\tTF(u,i) ---> ", current_transaction_factor)
                            new_transaction_factor = new_transaction_factor + current_transaction_factor
                            TF = TF + (time.time()-start_TF)
                            start_CF = time.time()
                            #current_community_factor = peerTrust.communityContextFactor2(current_trustee, new_interaction['trusteeDID'])
                            current_community_factor = peerTrust.bad_mouthing_attack_resilience(trustorDID, current_trustee, new_interaction['trusteeDID'], new_interaction['offerDID'])
                            print("\tCF(u) ---> ", current_community_factor, "\n")
                            new_community_factor = new_community_factor + current_community_factor
                            CF = CF + (time.time()-start_CF)
                            if current_community_factor > 0:
                                "It could be the case we don't have recommender for a new PO"
                                counter_new_CF_interactions += 1

                            counter_new_interactions +=1

            else:
                print("Currently, "+current_trustee+" has "+str(len(current_trustee_interactions))+" interactions in total\n")


            "Only updates and applies forgetting factor whether there are new Trustee interactions"
            if counter_new_interactions > 0:
                """ Updating the last value with the summation of new interactions"""
                new_satisfaction = round(self.recomputingTrustValue(last_satisfaction, (new_satisfaction/counter_new_interactions), FORGETTING_FACTOR), 4)
                new_credibility = round(self.recomputingTrustValue(last_credibility, (new_credibility/counter_new_interactions), FORGETTING_FACTOR), 4)
                new_transaction_factor = round(self.recomputingTrustValue(last_transaction_factor, (new_transaction_factor/counter_new_interactions), FORGETTING_FACTOR), 4)
            else:
                new_satisfaction = last_satisfaction
                new_credibility = last_credibility
                new_transaction_factor = last_transaction_factor

            if counter_new_CF_interactions > 0:
                new_community_factor = round(self.recomputingTrustValue(last_community_factor, (new_community_factor/counter_new_interactions), FORGETTING_FACTOR), 4)
            else:
                new_community_factor = last_community_factor

            information = trustInformationTemplate.trustTemplate()
            information["trustee"]["trusteeDID"] = current_trustee
            information["trustee"]["offerDID"] = offerDID
            information["trustee"]["trusteeSatisfaction"] = round(new_satisfaction, 4)
            information["trustor"]["trustorDID"] = trustorDID
            information["trustor"]["trusteeDID"] = current_trustee
            information["trustor"]["offerDID"] = offerDID
            information["trustor"]["credibility"] = round(new_credibility, 4)
            information["trustor"]["transactionFactor"] = round(new_transaction_factor, 4)
            information["trustor"]["communityFactor"] = round(new_community_factor, 4)

            "If we don't have recommendations, we only rely on ourself"
            if new_community_factor > 0:
                direct_weighting = round(random.uniform(0.65, 0.7),2)
            else:
                direct_weighting = 1

            information["trustor"]["direct_parameters"]["direct_weighting"] = direct_weighting
            information["trustor"]["indirect_parameters"]["recommendation_weighting"] = round(1-direct_weighting, 4)
            information["trustor"]["direct_parameters"]["interactionNumber"] = peerTrust.getInteractionNumber(trustorDID, current_trustee, offerDID)
            information["trustor"]["direct_parameters"]["totalInteractionNumber"] = peerTrust.getLastTotalInteractionNumber(current_trustee)
            information["trustor"]["direct_parameters"]["feedbackNumber"] = peerTrust.getTrusteeFeedbackNumberKafka(current_trustee)
            information["trustor"]["direct_parameters"]["feedbackOfferNumber"] = peerTrust.getOfferFeedbackNumberKafka(current_trustee, offerDID)
            information["trust_value"] = round(direct_weighting*(new_satisfaction*new_credibility*new_transaction_factor)+(1-direct_weighting)*new_community_factor,4)
            information["currentInteractionNumber"] = peerTrust.getCurrentInteractionNumber(trustorDID)
            information["initEvaluationPeriod"] = datetime.timestamp(datetime.now())-1000
            information["endEvaluationPeriod"] = datetime.timestamp(datetime.now())

            """ These values should be requested from other 5GZORRO components in future releases, in particular, 
            from the Calatog and SLA Breach Predictor"""

            start_satisfaction = time.time()


            availableAssets = 0
            totalAssets = 0
            availableAssetLocation = 0
            totalAssetLocation = 0
            consideredOffers = 0
            totalOffers= 0
            consideredOfferLocation = 0
            totalOfferLocation = 0

            "5GBarcelona"
            load_dotenv()
            barcelona_address = os.getenv('5GBARCELONA_CATALOG_A')
            response = requests.get(barcelona_address+"productCatalogManagement/v4/productOffering/did/"+offerDID)

            "5TONIC"
            #madrid_address = os.getenv('5TONIC_CATALOG_A')
            #response = requests.get(madrid_address+"productCatalogManagement/v4/productOffering/did/")

            response = json.loads(response.text)
            place = response['place'][0]['href']
            response = requests.get(place)
            response = json.loads(response.text)
            city = response['city']
            country = response['country']
            locality = response['locality']
            x_coordinate = response['geographicLocation']['geometry'][0]['x']
            y_coordinate = response['geographicLocation']['geometry'][0]['y']
            z_coordinate = response['geographicLocation']['geometry'][0]['z']


            for product_offer in statistic_catalog:
                if product_offer['provider'] == current_trustee:
                    totalAssets = product_offer['n_resource']
                    location = x_coordinate+"_"+y_coordinate+"_"+z_coordinate
                    if location in product_offer:
                        "Updating global variables"
                        totalAssetLocation = product_offer[location]
                        availableAssets = product_offer['active']
                        availableAssetLocation = product_offer['active'+"_"+location]
                        totalOffers = product_offer['active'+"_"+offer_type[offerDID].lower()]
                        totalOfferLocation = product_offer['active'+"_"+offer_type[offerDID].lower()+"_"+location]
                    break


            """Calculate the statistical parameters with respect to the considered offers"""
            for offer in considered_offer_list:
                if offer['trusteeDID'] == current_trustee:
                    consideredOffers+=1

                    "5GBarcelona"
                    load_dotenv()
                    barcelona_address = os.getenv('5GBARCELONA_CATALOG_A')
                    response = requests.get(barcelona_address+"productCatalogManagement/v4/productOffering/did/"+offer['offerDID'])

                    #madrid_address = os.getenv('5TONIC_CATALOG_A')
                    #response = requests.get(madrid_address+"productCatalogManagement/v4/productOffering/did/"+offer['offerDID'])

                    response = json.loads(response.text)

                    current_offer_place = response['place'][0]['href']
                    response = requests.get(current_offer_place)
                    response = json.loads(response.text)

                    "Check whether the POs have location information"
                    if "city" and "country" and "locality" in response:
                        current_offer_city = response['city']
                        current_offer_country = response['country']
                        current_offer_locality = response['locality']
                        current_offer_x_coordinate = response['geographicLocation']['geometry'][0]['x']
                        current_offer_y_coordinate = response['geographicLocation']['geometry'][0]['y']
                        current_offer_z_coordinate = response['geographicLocation']['geometry'][0]['z']

                        if city == current_offer_city and country == current_offer_country and locality == \
                                current_offer_locality and x_coordinate == current_offer_x_coordinate and \
                                y_coordinate == current_offer_y_coordinate and z_coordinate == current_offer_z_coordinate:
                            consideredOfferLocation+=1


            managedViolations = random.randint(1,20)
            predictedViolations = managedViolations + random.randint(0,5)
            executedViolations = random.randint(0,6)
            nonPredictedViolations = random.randint(0,2)

            managedOfferViolations = random.randint(4,22)
            predictedOfferViolations = managedOfferViolations + random.randint(0,8)
            executedOfferViolations = random.randint(0,4)
            nonPredictedOfferViolations = random.randint(0,3)

            provider_reputation = peerTrust.providerReputation(availableAssets, totalAssets,availableAssetLocation,
                                                               totalAssetLocation,managedViolations, predictedViolations,
                                                               executedViolations, nonPredictedViolations)

            information["trustor"]["direct_parameters"]["availableAssets"] = availableAssets
            information["trustor"]["direct_parameters"]["totalAssets"] = totalAssets
            information["trustor"]["direct_parameters"]["availableAssetLocation"] = availableAssetLocation
            information["trustor"]["direct_parameters"]["totalAssetLocation"] = totalAssetLocation
            information["trustor"]["direct_parameters"]["managedViolations"] = managedViolations
            information["trustor"]["direct_parameters"]["predictedViolations"] = predictedOfferViolations
            information["trustor"]["direct_parameters"]["executedViolations"] = executedViolations
            information["trustor"]["direct_parameters"]["nonPredictedViolations"] = nonPredictedViolations

            offer_reputation = peerTrust.offerReputation(consideredOffers, totalOffers, consideredOfferLocation,
                                                         totalOfferLocation, managedOfferViolations,
                                                         predictedOfferViolations, executedOfferViolations,
                                                         nonPredictedOfferViolations)

            information["trustor"]["direct_parameters"]["consideredOffers"] = consideredOffers
            information["trustor"]["direct_parameters"]["totalOffers"] = totalOffers
            information["trustor"]["direct_parameters"]["consideredOfferLocation"] = consideredOfferLocation
            information["trustor"]["direct_parameters"]["totalOfferLocation"] = totalOfferLocation
            information["trustor"]["direct_parameters"]["managedOfferViolations"] = managedOfferViolations
            information["trustor"]["direct_parameters"]["predictedOfferViolations"] = predictedOfferViolations
            information["trustor"]["direct_parameters"]["executedOfferViolations"] = executedOfferViolations
            information["trustor"]["direct_parameters"]["nonPredictedOfferViolations"] = nonPredictedOfferViolations
            satisfaction = satisfaction + (time.time()-start_satisfaction)


            start_satisfaction = time.time()

            provider_satisfaction = peerTrust.providerSatisfaction(trustorDID, current_trustee, provider_reputation, consumer)
            offer_satisfaction = peerTrust.offerSatisfaction(trustorDID, current_trustee, offerDID, offer_reputation)
            information["trustor"]["direct_parameters"]["providerSatisfaction"] = round(provider_satisfaction, 4)
            ps_weighting = round(random.uniform(0.4, 0.6),2)
            information["trustor"]["direct_parameters"]["PSWeighting"] = ps_weighting
            information["trustor"]["direct_parameters"]["offerSatisfaction"] = round(offer_satisfaction, 4)
            os_weighting = 1-ps_weighting
            information["trustor"]["direct_parameters"]["OSWeighting"] = os_weighting
            information["trustor"]["direct_parameters"]["providerReputation"] = round(provider_reputation, 4)
            information["trustor"]["direct_parameters"]["offerReputation"] = round(offer_reputation, 4)
            new_trustor_satisfaction = round(peerTrust.satisfaction(ps_weighting, os_weighting, provider_satisfaction, offer_satisfaction), 4)
            information["trustor"]["direct_parameters"]["userSatisfaction"] = round(self.recomputingTrustValue(last_trustor_satisfaction, new_trustor_satisfaction, FORGETTING_FACTOR), 4)
            new_trustor_satisfaction = information["trustor"]["direct_parameters"]["userSatisfaction"]
            satisfaction = satisfaction + (time.time()-start_satisfaction)

            """Updating the global average recommendations"""
            recommendation_list = consumer.readAllRecommenders(peerTrust.historical, trustorDID, current_trustee)
            global_average_recommendation = 0.0
            for recommendation in recommendation_list:
                global_average_recommendation += recommendation["average_recommendations"]

            if global_average_recommendation > 0:
                information["trustor"]["indirect_parameters"]["global_average_recommendations"] = global_average_recommendation / len(recommendation_list)

            new_recommendation_list = []
            """Updating the recommendation trust"""
            for recommendation in recommendation_list:
                satisfaction_variance = new_trustor_satisfaction - last_trustor_satisfaction
                new_recommendation_trust = self.recomputingRecommendationTrust(satisfaction_variance, recommendation, len(recommendation_list))
                recommendation["recommendation_trust"] = new_recommendation_trust
                new_recommendation_list.append(recommendation)

            if bool(new_recommendation_list):
                information["trustor"]["indirect_parameters"]["recommendations"] = new_recommendation_list

            response = {"trustorDID": trustorDID, "trusteeDID": {"trusteeDID": current_trustee, "offerDID": offerDID}, "trust_value": information["trust_value"], "currentInteractionNumber": information["currentInteractionNumber"],"evaluation_criteria": "Inter-domain", "initEvaluationPeriod": information["initEvaluationPeriod"],"endEvaluationPeriod": information["endEvaluationPeriod"]}

            print("\nNew Trust values after considering new interactions of "+current_trustee+":")
            print("\tα ---> ", direct_weighting)
            print("\tS(u,i) ---> ", new_satisfaction)
            print("\tCr(p(u,i)) ---> ", new_credibility)
            print("\tTF(u,i) ---> ", new_transaction_factor)
            print("\tβ ---> ", round(1-direct_weighting, 3))
            print("\tCF(u) ---> ", new_community_factor)


            print("\nPrevious Trust score of "+trustorDID+" on "+current_trustee+" --->", last_trust_value, " -- New trust score --->", information["trust_value"])

            peerTrust.historical.append(information)

            compute_time = compute_time + (time.time()-start_time)

            print("\n$$$$$$$$$$$$$$ Ending trust computation procces on ",current_trustee, " $$$$$$$$$$$$$$\n")

            requests.post("http://localhost:5002/store_trust_level", data=json.dumps(information).encode("utf-8"))

        return response

    def recomputingRecommendationTrust(self, satisfaction_variance, recommendation_object, total_recommendations):
        """ This method updates the recommendation trust (RT) value after new interactions between a trustor and a trustee.
        The method makes use of the satisfaction and global average recommendation variances to increase or decrease the RT."""

        mean_variance =  pow(recommendation_object["last_recommendation"] - recommendation_object["global_average_recommendations"], 2) / total_recommendations
        if satisfaction_variance > 0 and mean_variance > 0:
            new_recommendation_trust = (1 + satisfaction_variance)*(mean_variance/10) + recommendation_object["recommendation_trust"]
            if new_recommendation_trust > 1.0:
                new_recommendation_trust = 1.0
            return new_recommendation_trust
        elif satisfaction_variance < 0 and mean_variance < 0:
            new_recommendation_trust = (1 + abs(satisfaction_variance))*(abs(mean_variance)/10) + recommendation_object["recommendation_trust"]
            if new_recommendation_trust > 1.0:
                new_recommendation_trust = 1.0
            return new_recommendation_trust
        elif satisfaction_variance < 0 and mean_variance > 0:
            new_recommendation_trust = recommendation_object["recommendation_trust"] - (1 - satisfaction_variance)*(mean_variance/10)
            if new_recommendation_trust < 0:
                new_recommendation_trust = 0
            return new_recommendation_trust
        elif satisfaction_variance > 0 and mean_variance < 0:
            new_recommendation_trust = recommendation_object["recommendation_trust"] - (1 + satisfaction_variance)*(abs(mean_variance)/10)
            if new_recommendation_trust < 0:
                new_recommendation_trust = 0
            return new_recommendation_trust
        elif mean_variance == 0:
            return recommendation_object["recommendation_trust"]


    def recomputingTrustValue(self, historical_value, new_value, forgetting_factor):
        """ This method applies a sliding window to compute a new trust score. Besides, we avoid new values can
        immediately change an historical value through the forgetting factor """

        return (1-forgetting_factor) * historical_value + forgetting_factor * new_value



class store_trust_level(Resource):
    def post(self):
        """ This method is employed to register direct trust in our internal database """
        global storage_time

        req = request.data.decode("utf-8")
        information = json.loads(req)

        print("$$$$$$$$$$$$$$ Starting trust information storage process $$$$$$$$$$$$$$\n")

        start_time = time.time()

        print("Registering a new trust interaction between two domains in the Data Lake\n")
        data = "{\"trustorDID\": \""+information["trustor"]["trustorDID"]+"\", \"trusteeDID\": \""+information["trustee"]["trusteeDID"]+"\", \"offerDID\": \""+information["trustee"]["offerDID"]+"\",\"userSatisfaction\": "+str(information["trustor"]["direct_parameters"]["userSatisfaction"])+", \"interactionNumber\": "+str(information["trustor"]["direct_parameters"]["interactionNumber"])+", \"totalInteractionNumber\": "+str(information["trustor"]["direct_parameters"]["totalInteractionNumber"])+", \"currentInteractionNumber\": "+str(information["currentInteractionNumber"])+"}\""
        print(data,"\n")
        print("Sending new trust information in the historical generated by the Trust Management Framework \n")
        print(information)
        print("\nStoring new trust information in our internal MongoDB database\n")

        print("\n$$$$$$$$$$$$$$ Ending trust information storage process $$$$$$$$$$$$$$\n")

        """list_trustee_interactions = {}
        query = mongoDB.find_one(information["trustee"]["trusteeDID"])
        if query is not None:
            list_trustee_interactions[information["trustee"]["trusteeDID"]].append(information)
            mongoDB.update_one(query, list_trustee_interactions)
        else:
            list_trustee_interactions[information["trustee"]["trusteeDID"]] = [information]
            mongoDB.insert_one(list_trustee_interactions)"""

        mongoDB.insert_one(information)

        storage_time = storage_time + (time.time()-start_time)

        return 200


class update_trust_level(Resource):
    def post(self):
        """ This method updates a trust score based on certain SLA events. More events need to be considered,
        it is only an initial version"""
        global offer_type

        req = request.data.decode("utf-8")
        information = json.loads(req)

        print("\n$$$$$$$$$$$$$$ Starting update trust level process on", information["offerDID"], "$$$$$$$$$$$$$$\n")

        offerDID = information["offerDID"]

        " Equation for calculating new trust --> n_ts = n_ts+o_ts*((1-n_ts)/10) from security events"
        last_trust_score = consumer.readAllInformationTrustValue(peerTrust.historical, offerDID)

        """ Defining a new thread per each trust relationship as well as an event to stop the relationship"""
        event = threading.Event()
        x = threading.Thread(target=self.reward_and_punishment_based_on_security, args=(last_trust_score, offer_type, event,))
        threads_security.append({offerDID:x, "stop_event": event})
        x.start()

        """ Defining a new thread per each trust relationship as well as an event to stop the relationship"""
        event = threading.Event()
        x = threading.Thread(target=self.reward_and_punishment_based_on_SLA_events, args=(last_trust_score, event,))
        threads_sla.append({offerDID:x, "stop_event": event})
        x.start()

        return 200

    def reward_and_punishment_based_on_security(self, last_trust_score, offer_type, event):
        """" This method is in charge of updating an ongoing trust relationship after each 30 minutes employing security
        monitoring events reported by the Security Analysis Service"""

        "Sliding window weighting with respect to the forgetting factor"
        TOTAL_RW = 0.9
        NOW_RW = 1 - TOTAL_RW

        "Sliding window definition IN SECONDS"
        CURRENT_TIME_WINDOW = 1800

        total_reward_and_punishment = float(last_trust_score["trustor"]["reward_and_punishment_security"])
        offerDID = last_trust_score["trustor"]["offerDID"]
        current_offer_type = offer_type[offerDID]

        while not event.isSet():
            time.sleep(CURRENT_TIME_WINDOW)
            current_reward_and_punishment = 0.0

            if current_offer_type.lower() == 'ran' or current_offer_type.lower() == 'spectrum':
                current_reward_and_punishment = self.generic_reward_and_punishment_based_on_security(CURRENT_TIME_WINDOW, offerDID, current_offer_type, 0.4, 0.1, 0.1, 0.4)
            elif current_offer_type.lower() == 'edge' or current_offer_type.lower() == 'cloud':
                current_reward_and_punishment = self.generic_reward_and_punishment_based_on_security(CURRENT_TIME_WINDOW, offerDID, current_offer_type, 0.2, 0.35, 0.25, 0.2)
            elif current_offer_type.lower() == 'vnf' or current_offer_type.lower() == 'cnf':
                current_reward_and_punishment = self.generic_reward_and_punishment_based_on_security(CURRENT_TIME_WINDOW, offerDID, current_offer_type, 0.233, 0.3, 0.233, 0.233)
            elif current_offer_type.lower() == 'network service' or current_offer_type.lower() == 'slice':
                current_reward_and_punishment = self.generic_reward_and_punishment_based_on_security(CURRENT_TIME_WINDOW, offerDID, current_offer_type, 0.233, 0.3, 0.233, 0.233)

            if current_reward_and_punishment >= 0:
                final_security_reward_and_punishment = TOTAL_RW * total_reward_and_punishment + NOW_RW * current_reward_and_punishment

                if final_security_reward_and_punishment >= 0.5:
                    reward_and_punishment = final_security_reward_and_punishment - 0.5
                    n_ts = float(last_trust_score ["trust_value"]) + reward_and_punishment * ((1-float(last_trust_score ["trust_value"]))/10)
                    new_trust_score = min(n_ts, 1)
                elif final_security_reward_and_punishment < 0.5:
                    "The lower value the higher punishment"
                    reward_and_punishment = 0.5 - final_security_reward_and_punishment
                    n_ts = float(last_trust_score ["trust_value"]) - reward_and_punishment * ((1-float(last_trust_score ["trust_value"]))/10)
                    new_trust_score = max(0, n_ts)
            else:
                new_trust_score = last_trust_score ["trust_value"]
                final_security_reward_and_punishment = total_reward_and_punishment
                print("No new Security Analysis events have been generated in the last time-window")

            print("\n\tPrevious Trust Score", last_trust_score ["trust_value"], " --- Updated Trust Score After Security-based Reward and Punishment --->", round(new_trust_score, 4), "\n")
            last_trust_score["trustor"]["reward_and_punishment_security"] = final_security_reward_and_punishment
            last_trust_score["trust_value"] = round(new_trust_score, 4)
            last_trust_score["endEvaluationPeriod"] = datetime.timestamp(datetime.now())

            peerTrust.historical.append(last_trust_score)
            #mongoDB.insert_one(last_trust_score)
            itm = mongoDB.find_one({'trustee.offerDID': offerDID, 'trustor.trusteeDID': last_trust_score["trustor"]["trusteeDID"]})
            if itm != None:
                mongoDB.replace_one({'_id': itm.get('_id')}, last_trust_score, True)


    def get_resource_list_network_service_offer(self, offerDID):
        """ This method retrieves one or more resources involved in a Network Service/Slice Product Offering"""
        "5GBarcelona"
        load_dotenv()
        barcelona_address = os.getenv('5GBARCELONA_CATALOG_A')
        response = requests.get(barcelona_address+"productCatalogManagement/v4/productOffering/did/"+offerDID)
        "5TONIC"
        #madrid_address = os.getenv('5TONIC_CATALOG_A')
        #response = requests.get(madrid_address+"productCatalogManagement/v4/productOffering/did/")

        response = json.loads(response.text)

        product_specification = response['productSpecification']['href']
        response = requests.get(product_specification)
        response = json.loads(response.text)
        service_specification = response['serviceSpecification'][0]['href']
        response = requests.get(service_specification)
        response = json.loads(response.text)
        resource_specification = response['resourceSpecification']

        return resource_specification

    def generic_reward_and_punishment_based_on_security(self, CURRENT_TIME_WINDOW, offerDID, offer_type, CONN_DIMENSION_WEIGHTING,
                                                        NOTICE_DIMENSION_WEIGHTING, WEIRD_DIMENSION_WEIGHTING,
                                                        STATS_DIMENSION_WEIGHTING):
        """ This methods collects from ElasticSearch new security effects and computes the reward or punishment based on
        the type of offers. So, different sets of events are linked to each PO as well as weighting factors """
        "Global variable definition"
        global icmp_orig_pkts
        global tcp_orig_pkts
        global udp_orig_pkts

        "Local variable definition"
        conn_info = []
        notice_info = []
        weird_info = []
        stats_info = []

        first_conn_value = 0
        first_notice_value = 0
        first_weird_value = 0
        first_stats_value = 0

        indices_info = self.get_ELK_information(offerDID)

        if len(indices_info) == 0:
            print('No matches were detected by the ', offerDID, 'index in the Security Analysis Service logs')

        for index in indices_info:
            for hit in index["hits"]["hits"]:
                if "conn.log" in hit["_source"]["log"]["file"]["path"] and hit not in conn_info:
                    conn_info.append(hit)
                elif "notice.log" in hit["_source"]["log"]["file"]["path"] and hit not in notice_info:
                    notice_info.append(hit)
                elif "weird.log" in hit["_source"]["log"]["file"]["path"] and hit not in weird_info:
                    weird_info.append(hit)
                elif "stats.log" in hit["_source"]["log"]["file"]["path"] and hit not in stats_info:
                    stats_info.append(hit)

            "Previously, we had multiple VMs linked to the same slices"
            #first_conn_value = (first_conn_value + self.conn_log(CURRENT_TIME_WINDOW, conn_info))/len(indices_info)
            #first_notice_value = (first_notice_value + self.notice_log(CURRENT_TIME_WINDOW, offer_type, notice_info))/len(indices_info)
            #first_weird_value = (first_weird_value + self.weird_log(CURRENT_TIME_WINDOW, offer_type, weird_info))/len(indices_info)
            #first_stats_value = (first_stats_value + self.stats_log(CURRENT_TIME_WINDOW, icmp_orig_pkts, tcp_orig_pkts, udp_orig_pkts, stats_info))/len(indices_info)

        "Now, we have a SAS VNF which collects all information from multiple Network Services in the same Network Slice"
        if len(indices_info) > 0:
            first_conn_value = self.conn_log(CURRENT_TIME_WINDOW, conn_info)
            first_notice_value = self.notice_log(CURRENT_TIME_WINDOW, offer_type, notice_info)
            first_weird_value = self.weird_log(CURRENT_TIME_WINDOW, offer_type, weird_info)
            first_stats_value = self.stats_log(CURRENT_TIME_WINDOW, icmp_orig_pkts, tcp_orig_pkts, udp_orig_pkts, stats_info)

            if first_conn_value and first_stats_value and first_weird_value and first_notice_value == 0:
                "We don't have new SAS events in the current time-window"
                return -1
            return CONN_DIMENSION_WEIGHTING * first_conn_value + NOTICE_DIMENSION_WEIGHTING * first_notice_value \
                   + WEIRD_DIMENSION_WEIGHTING * first_weird_value + STATS_DIMENSION_WEIGHTING * first_stats_value
        else:
            "In this case, the PO does not have a Service Specification and in consequence the SAS cannot generate an index"
            return -1

    def get_ELK_information(self, offerDID):
        """ This method gets all new index from the ELK"""
        load_dotenv()
        elk_address = os.getenv('ELK')

        response = requests.get(elk_address+'_cat/indices')
        response = response.text
        with open('output.txt', 'w') as my_data_file:
            my_data_file.write(response)
            my_data_file.close()

        instances = []
        indices_info = []

        load_dotenv()
        barcelona_address = os.getenv('5GBARCELONA_CATALOG_A')
        response = requests.get(barcelona_address+"productCatalogManagement/v4/productOffering/did/"+offerDID)
        "5TONIC"
        #madrid_address = os.getenv('5TONIC_CATALOG_A')
        #response = requests.get(madrid_address+"productCatalogManagement/v4/productOffering/did/")

        response = json.loads(response.text)
        product_specification = response['productSpecification']['href']
        response = requests.get(product_specification)
        response = json.loads(response.text)
        if len(response['serviceSpecification']) > 0:
            response = response['serviceSpecification'][0]['href']
            response = requests.get(response)
            response = json.loads(response.text)
            id_service_specification = response['serviceSpecCharacteristic'][0]['serviceSpecCharacteristicValue'][0]['value']['value']
        else:
            id_service_specification = 'None'
            print('The POs does not contain the serviceSpecification field')

        with open('output.txt', 'r') as f:
            for line in f:
                if 'yellow' in line:
                    indice = line.split('open ')[1].split(" ")[0]
                    if id_service_specification in indice:
                        instances.append(indice)

        for instance in instances:
            response = requests.post(elk_address+instance+'/_search')
            response = json.loads(response.text)
            indices_info.append(response)

        return indices_info

    def conn_log(self, time_window, conn_info):
        """ This function will compute the security level of an ongoing trust relationship between two operators from the
        percentage of network packages correctly sent """
        global icmp_orig_pkts
        global tcp_orig_pkts
        global udp_orig_pkts

        "Weight definition"
        ICMP = 0.3
        TCP = 0.3
        UDP = 0.4

        "Variable definition"
        icmp_orig_pkts = 0
        tcp_orig_pkts = 0
        udp_orig_pkts = 0
        icmp_resp_pkts = 0
        tcp_resp_pkts = 0
        udp_resp_pkts = 0

        timestamp = time.time()
        timestamp_limit = timestamp - time_window

        for log in conn_info:
            timestamp_log = time.mktime(time.strptime(log["_source"]["@timestamp"].split(".")[0], '%Y-%m-%dT%H:%M:%S'))
            if timestamp_log >= timestamp_limit:
                if log["_source"]["network"]["transport"] == "icmp":
                    icmp_orig_pkts += icmp_orig_pkts + log["_source"]["source"]["packets"]
                    icmp_resp_pkts += icmp_resp_pkts + log["_source"]["destination"]["packets"]
                elif log["_source"]["network"]["transport"] == "tcp":
                    tcp_orig_pkts += tcp_orig_pkts + log["_source"]["source"]["packets"]
                    tcp_resp_pkts += tcp_resp_pkts + log["_source"]["destination"]["packets"]
                elif log["_source"]["network"]["transport"] == "udp":
                    udp_orig_pkts += udp_orig_pkts + log["_source"]["source"]["packets"]
                    udp_resp_pkts += udp_orig_pkts + log["_source"]["destination"]["packets"]

        try:
            icmp_packet_hit_rate = icmp_resp_pkts/icmp_orig_pkts
        except ZeroDivisionError:
            icmp_packet_hit_rate = 0
        try:
            tcp_packet_hit_rate = tcp_resp_pkts/tcp_orig_pkts
        except ZeroDivisionError:
            tcp_packet_hit_rate = 0
        try:
            udp_packet_hit_rate = udp_resp_pkts/udp_orig_pkts
        except ZeroDivisionError:
            udp_packet_hit_rate = 0

        final_conn_value = ICMP * icmp_packet_hit_rate + TCP * tcp_packet_hit_rate + UDP * udp_packet_hit_rate

        return final_conn_value

    def notice_log(self, time_window, offer_type, notice_info):
        """ This function will compute the security level of an ongoing trust relationship between two operators from
         critical security events detected by the Zeek """

        "Generic label definition"
        TOO_MUCH_LOSS = "CaptureLoss::Too_Much_Loss"
        TOO_LITTLE_TRAFFIC = " CaptureLoss::Too_Little_Traffic"
        WEIRD_ACTIVITY = "Weird::Activity"
        PACKET_FILTER = "PacketFilter::Dropped_Packets"
        SOFTWARE_VULNERABLE = "Software::Vulnerable_Version"
        SQL_INJECTION_ATTACKER = "HTTP::SQL_Injection_Attacker"
        SQL_INJECTION_VICTIM = "HTTP::SQL_Injection_Victim"
        PASSWORD_GUESSING = "SSH::Password_Guessing"

        "Edge specific label definition"
        TOO_LONG_TO_COMPILE_FAILURE = "PacketFilter::Too_Long_To_Compile_Filter"
        ADDRESS_SCAN = "Scan::Address_Scan"
        PORT_SCAN = "Scan::Port_Scan"
        MALWARE_HASH = "TeamCymruMalwareHashRegistry::Match"
        TRACEROUTE = "Traceroute::Detected"
        BLOCKED_HOST = "SMTP::Blocklist_Blocked_Host"
        SUSPICIOUS_ORIGINATION = "SMTP::Suspicious_Origination"
        CERTIFICATE_EXPIRED = "SSL::Certificate_Expired"
        CERTIFICATE_NOT_VALID = "SSL::Certificate_Not_Valid_Yet"
        SSL_HEARTBEAT_ATTACK = "Heartbleed::SSL_Heartbeat_Attack"
        SSL_HEARTBEAT_ATTACK_SUCCESS = "Heartbleed::SSL_Heartbeat_Attack_Success"
        SSL_WEAK_KEY = "SSL::Weak_Key"
        SSL_OLD_VERSION = "SSL::Old_Version"
        SSL_WEAK_CIPHER = "SSL::Weak_Cipher"

        "Cloud specific label definition"
        SERVER_FOUND = "ProtocolDetector::Server_Found"
        BRUTEFORCING = "FTP::Bruteforcing"

        "VNF/CNF specific label definition"
        SENSITIVE_SIGNATURE = "Signatures::Sensitive_Signature"
        COMPILE_FAILURE_PACKET_FILTER = "PacketFilter::Compile_Failure"
        INSTALL_FAILURE = "PacketFilter::Install_Failure"
        CONTENT_GAP = "Conn::Content_Gap"

        "By default notice.log file is gathered after 15 minutes"
        TIME_MONITORING_EVENT = 900
        LAST_FIVE_TIME_MONITORING_EVENT = 4500

        "List of general labels"
        events_to_monitor = []
        events_to_monitor.append(TOO_MUCH_LOSS)
        events_to_monitor.append(TOO_LITTLE_TRAFFIC)
        events_to_monitor.append(WEIRD_ACTIVITY)
        events_to_monitor.append(PACKET_FILTER)
        events_to_monitor.append(SOFTWARE_VULNERABLE)
        events_to_monitor.append(PASSWORD_GUESSING)

        "List of specific labels regarding the type of offer"
        edge_events_to_monitor = []
        edge_events_to_monitor.append(PORT_SCAN)
        edge_events_to_monitor.append(TOO_LONG_TO_COMPILE_FAILURE)
        edge_events_to_monitor.append(COMPILE_FAILURE_PACKET_FILTER)
        edge_events_to_monitor.append(INSTALL_FAILURE)
        edge_events_to_monitor.append(MALWARE_HASH)
        edge_events_to_monitor.append(TRACEROUTE)
        edge_events_to_monitor.append(ADDRESS_SCAN)
        edge_events_to_monitor.append(BRUTEFORCING)
        edge_events_to_monitor.append(BLOCKED_HOST)
        edge_events_to_monitor.append(SUSPICIOUS_ORIGINATION)
        edge_events_to_monitor.append(CERTIFICATE_EXPIRED)
        edge_events_to_monitor.append(CERTIFICATE_NOT_VALID)
        edge_events_to_monitor.append(SSL_HEARTBEAT_ATTACK)
        edge_events_to_monitor.append(SSL_HEARTBEAT_ATTACK_SUCCESS)
        edge_events_to_monitor.append(SSL_WEAK_KEY)
        edge_events_to_monitor.append(SSL_OLD_VERSION)
        edge_events_to_monitor.append(SSL_WEAK_CIPHER)
        edge_events_to_monitor.append(SQL_INJECTION_ATTACKER)
        edge_events_to_monitor.append(SQL_INJECTION_VICTIM)

        cloud_events_to_monitor = []
        cloud_events_to_monitor.append(PORT_SCAN)
        cloud_events_to_monitor.append(COMPILE_FAILURE_PACKET_FILTER)
        cloud_events_to_monitor.append(INSTALL_FAILURE)
        cloud_events_to_monitor.append(SERVER_FOUND)
        cloud_events_to_monitor.append(MALWARE_HASH)
        cloud_events_to_monitor.append(TRACEROUTE)
        cloud_events_to_monitor.append(ADDRESS_SCAN)
        cloud_events_to_monitor.append(BRUTEFORCING)
        cloud_events_to_monitor.append(CERTIFICATE_EXPIRED)
        cloud_events_to_monitor.append(CERTIFICATE_NOT_VALID)
        cloud_events_to_monitor.append(SSL_HEARTBEAT_ATTACK)
        cloud_events_to_monitor.append(SSL_HEARTBEAT_ATTACK_SUCCESS)
        cloud_events_to_monitor.append(SSL_WEAK_KEY)
        cloud_events_to_monitor.append(SSL_OLD_VERSION)
        cloud_events_to_monitor.append(SSL_WEAK_CIPHER)
        cloud_events_to_monitor.append(SQL_INJECTION_ATTACKER)
        cloud_events_to_monitor.append(SQL_INJECTION_VICTIM)

        vnf_cnf_events_to_monitor = []
        vnf_cnf_events_to_monitor.append(SENSITIVE_SIGNATURE)
        vnf_cnf_events_to_monitor.append(COMPILE_FAILURE_PACKET_FILTER)
        vnf_cnf_events_to_monitor.append(INSTALL_FAILURE)
        vnf_cnf_events_to_monitor.append(MALWARE_HASH)
        vnf_cnf_events_to_monitor.append(TRACEROUTE)
        vnf_cnf_events_to_monitor.append(ADDRESS_SCAN)
        vnf_cnf_events_to_monitor.append(PORT_SCAN)
        vnf_cnf_events_to_monitor.append(CONTENT_GAP)

        "Variable definition"
        actual_event_number = 0
        previous_monitoring_window_event_number = 0
        last_five_monitoring_window_event_number = 0

        timestamp = time.time()
        timestamp_limit = timestamp - time_window

        previous_event_monitoring_timestamp = timestamp - TIME_MONITORING_EVENT
        last_five_event_monitoring_timestamp = timestamp - LAST_FIVE_TIME_MONITORING_EVENT

        for log in notice_info:
            timestamp_log = time.mktime(time.strptime(log["_source"]["@timestamp"].split(".")[0], '%Y-%m-%dT%H:%M:%S'))
            if log["_source"]["zeek"]["notice"]["name"] in events_to_monitor and timestamp_log >= timestamp_limit:
                actual_event_number += 1
            elif log["_source"]["zeek"]["notice"]["name"] in events_to_monitor and timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_event_number += 1
                last_five_monitoring_window_event_number += 1
            elif log["_source"]["zeek"]["notice"]["name"] in events_to_monitor and timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_event_number += 1
            elif offer_type.lower() == 'edge' and log["_source"]["zeek"]["notice"]["name"] in edge_events_to_monitor and \
                    timestamp_log >= timestamp_limit:
                actual_event_number += 1
            elif offer_type.lower() == 'edge' and log["_source"]["zeek"]["notice"]["name"] in edge_events_to_monitor and \
                    timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_event_number += 1
                last_five_monitoring_window_event_number += 1
            elif offer_type.lower() == 'edge' and log["_source"]["zeek"]["notice"]["name"] in edge_events_to_monitor and \
                    timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_event_number += 1
            elif offer_type.lower() == 'cloud' and log["_source"]["zeek"]["notice"]["name"] in cloud_events_to_monitor and \
                    timestamp_log >= timestamp_limit:
                actual_event_number += 1
            elif offer_type.lower() == 'cloud' and log["_source"]["zeek"]["notice"]["name"] in cloud_events_to_monitor and \
                    timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_event_number += 1
                last_five_monitoring_window_event_number += 1
            elif offer_type.lower() == 'cloud' and log["_source"]["zeek"]["notice"]["name"] in cloud_events_to_monitor and \
                    timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_event_number += 1
            elif offer_type.lower() == 'vnf' or offer_type.lower() == 'cnf' and log["_source"]["zeek"]["notice"]["name"] \
                    in vnf_cnf_events_to_monitor and timestamp_log >= timestamp_limit:
                actual_event_number += 1
            elif offer_type.lower() == 'vnf' or offer_type.lower() == 'cnf' and log["_source"]["zeek"]["notice"]["name"] \
                    in vnf_cnf_events_to_monitor and timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_event_number += 1
                last_five_monitoring_window_event_number += 1
            elif offer_type.lower() == 'vnf' or offer_type.lower() == 'cnf' and log["_source"]["zeek"]["notice"]["name"] \
                    in vnf_cnf_events_to_monitor and timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_event_number += 1

        try:
            last_window_notice_events = actual_event_number/(previous_monitoring_window_event_number + actual_event_number)
        except ZeroDivisionError:
            last_window_notice_events = 0

        try:
            five_last_window_notice_events = actual_event_number / actual_event_number + ( last_five_monitoring_window_event_number / 5)
        except ZeroDivisionError:
            five_last_window_notice_events = 0

        final_notice_value = 1 - ((last_window_notice_events + five_last_window_notice_events) / 2)


        return final_notice_value

    def weird_log(self, time_window, offer_type, weird_info):
        """ This function will compute the security level of an ongoing trust relationship between two operators from
         weird events detected by the Zeek """

        "Label definition"
        DNS_UNMTATCHED_REPLY = "dns_unmatched_reply"
        ACTIVE_CONNECTION_REUSE = "active_connection_reuse"
        SPLIT_ROUTING = "possible_split_routing"
        INAPPROPIATE_FIN = "inappropriate_FIN"
        FRAGMENT_PAKCKET = "fragment_with_DF"
        BAD_ICMP_CHECKSUM = "bad_ICMP_checksum"
        BAD_UDP_CHECKSUM = "bad_UDP_checksum"
        BAD_TCP_CHECKSUM = "bad_TCP_checksum"
        TCP_CHRISTMAS = "TCP_Christmas"
        UNSCAPED_PERCENTAGE_URI = "unescaped_%_in_URI"
        ILLEGAL_ENCODING = "base64_illegal_encoding"
        BAD_HTTP_REPLY = "bad_HTTP_reply"
        MALFORMED_SSH_IDENTIFICATION = "malformed_ssh_identification"
        MALFORMED_SSH_VERSION = "malformed_ssh_version"

        "List of labels"
        weird_event_list = []
        weird_event_list.append(DNS_UNMTATCHED_REPLY)
        weird_event_list.append(ACTIVE_CONNECTION_REUSE)
        weird_event_list.append(ILLEGAL_ENCODING)

        "List of specific labels regarding the type of offer"
        edge_events_to_monitor = []
        edge_events_to_monitor.append(SPLIT_ROUTING)
        edge_events_to_monitor.append(BAD_ICMP_CHECKSUM)
        edge_events_to_monitor.append(BAD_UDP_CHECKSUM)
        edge_events_to_monitor.append(BAD_TCP_CHECKSUM)
        edge_events_to_monitor.append(TCP_CHRISTMAS)
        edge_events_to_monitor.append(UNSCAPED_PERCENTAGE_URI)
        edge_events_to_monitor.append(BAD_HTTP_REPLY)

        cloud_events_to_monitor = []
        cloud_events_to_monitor.append(SPLIT_ROUTING)
        cloud_events_to_monitor.append(BAD_ICMP_CHECKSUM)
        cloud_events_to_monitor.append(BAD_UDP_CHECKSUM)
        cloud_events_to_monitor.append(BAD_TCP_CHECKSUM)
        cloud_events_to_monitor.append(TCP_CHRISTMAS)
        cloud_events_to_monitor.append(BAD_HTTP_REPLY)

        vnf_cnf_events_to_monitor = []
        vnf_cnf_events_to_monitor.append(INAPPROPIATE_FIN)
        vnf_cnf_events_to_monitor.append(FRAGMENT_PAKCKET)
        vnf_cnf_events_to_monitor.append(MALFORMED_SSH_IDENTIFICATION)
        vnf_cnf_events_to_monitor.append(MALFORMED_SSH_VERSION)


        "Variable definition"
        actual_weird_event_number = 0
        previous_monitoring_window_weird_event_number = 0
        last_five_monitoring_window_weird_event_number = 0

        "By default weird.log file is gathered after 15 minutes, VERIFY!"
        TIME_MONITORING_WEIRD_EVENT = 900
        LAST_FIVE_TIME_MONITORING_WEIRD_EVENT = 4500

        timestamp = time.time()
        timestamp_limit = timestamp - time_window

        previous_event_monitoring_timestamp = timestamp - TIME_MONITORING_WEIRD_EVENT
        last_five_event_monitoring_timestamp = timestamp - LAST_FIVE_TIME_MONITORING_WEIRD_EVENT

        for log in weird_info:
            timestamp_log = time.mktime(time.strptime(log["_source"]["@timestamp"].split(".")[0], '%Y-%m-%dT%H:%M:%S'))
            if log["_source"]["zeek"]["weird"]["name"] in weird_event_list and timestamp_log >= timestamp_limit:
                actual_weird_event_number += 1
            elif log["_source"]["zeek"]["weird"]["name"] in weird_event_list and timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_weird_event_number += 1
                last_five_monitoring_window_weird_event_number += 1
            elif log["_source"]["zeek"]["weird"]["name"] in weird_event_list and timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_weird_event_number += 1
            elif offer_type.lower() == 'edge' and log["_source"]["zeek"]["weird"]["name"] in edge_events_to_monitor and \
                    timestamp_log >= timestamp_limit:
                actual_weird_event_number += 1
            elif offer_type.lower() == 'edge' and log["_source"]["zeek"]["weird"]["name"] in edge_events_to_monitor and \
                    timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_weird_event_number += 1
                last_five_monitoring_window_weird_event_number += 1
            elif offer_type.lower() == 'edge' and log["_source"]["zeek"]["weird"]["name"] in edge_events_to_monitor and \
                    timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_weird_event_number += 1
            elif offer_type.lower() == 'cloud' and log["_source"]["zeek"]["weird"]["name"] in cloud_events_to_monitor and \
                    timestamp_log >= timestamp_limit:
                actual_weird_event_number += 1
            elif offer_type.lower() == 'cloud' and log["_source"]["zeek"]["weird"]["name"] in cloud_events_to_monitor and \
                    timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_weird_event_number += 1
                last_five_monitoring_window_weird_event_number += 1
            elif offer_type.lower() == 'cloud' and log["_source"]["zeek"]["weird"]["name"] in cloud_events_to_monitor and \
                    timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_weird_event_number += 1
            elif offer_type.lower() == 'vnf' or offer_type.lower() == 'cnf' and log["_source"]["zeek"]["weird"]["name"] \
                    in vnf_cnf_events_to_monitor and timestamp_log >= timestamp_limit:
                actual_weird_event_number += 1
            elif offer_type.lower() == 'vnf' or offer_type.lower() == 'cnf' and log["_source"]["zeek"]["weird"]["name"] \
                    in vnf_cnf_events_to_monitor and timestamp_log >= previous_event_monitoring_timestamp:
                previous_monitoring_window_weird_event_number += 1
                last_five_monitoring_window_weird_event_number += 1
            elif offer_type.lower() == 'vnf' or offer_type.lower() == 'cnf' and log["_source"]["zeek"]["weird"]["name"] \
                    in vnf_cnf_events_to_monitor and timestamp_log >= last_five_event_monitoring_timestamp:
                last_five_monitoring_window_weird_event_number += 1

        try:
            last_window_weird_events = actual_weird_event_number/(previous_monitoring_window_weird_event_number + actual_weird_event_number)
        except ZeroDivisionError:
            last_window_weird_events = 0

        try:
            five_last_window_weird_events = actual_weird_event_number / actual_weird_event_number + (last_five_monitoring_window_weird_event_number / 5)
        except ZeroDivisionError:
            five_last_window_weird_events = 0

        final_weird_value = 1 - (( last_window_weird_events + five_last_window_weird_events ) / 2)

        return final_weird_value

    def stats_log(self, time_window, icmp_sent_pkts, tcp_sent_pkts, udp_sent_pkts, stat_info):
        """ This function will compute the security level of an ongoing trust relationship between two operators from the
        percentage of network packages sent and the packets finally analyzed by Zeek"""

        "Global variable definition"
        global icmp_orig_pkts
        global tcp_orig_pkts
        global udp_orig_pkts

        "Weight definition"
        ICMP = 0.3
        TCP = 0.3
        UDP = 0.4

        "Variable definition"
        icmp_orig_pkts = icmp_sent_pkts
        tcp_orig_pkts = tcp_sent_pkts
        udp_orig_pkts = udp_sent_pkts
        icmp_pkts_analyzed_by_zeek = 0
        tcp_pkts_analyzed_by_zeek = 0
        udp_pkts_analyzed_by_zeek = 0

        timestamp = time.time()
        timestamp_limit = timestamp - time_window

        for log in stat_info:
            timestamp_log = time.mktime(time.strptime(log["_source"]["@timestamp"].split(".")[0], '%Y-%m-%dT%H:%M:%S'))
            if timestamp_log >= timestamp_limit:
                icmp_pkts_analyzed_by_zeek += icmp_pkts_analyzed_by_zeek + log["_source"]["zeek"]["connections"]["icmp"]["count"]
                tcp_pkts_analyzed_by_zeek += tcp_pkts_analyzed_by_zeek + log["_source"]["zeek"]["connections"]["tcp"]["count"]
                udp_pkts_analyzed_by_zeek += udp_pkts_analyzed_by_zeek + log["_source"]["zeek"]["connections"]["udp"]["count"]

        try:
            icmp_packet_rate_analyzed_by_zeek = icmp_pkts_analyzed_by_zeek/icmp_orig_pkts
        except ZeroDivisionError:
            icmp_packet_rate_analyzed_by_zeek = 0
        try:
            tcp_packet_rate_analyzed_by_zeek = tcp_pkts_analyzed_by_zeek/tcp_orig_pkts
        except ZeroDivisionError:
            tcp_packet_rate_analyzed_by_zeek = 0
        try:
            udp_packet_rate_analyzed_by_zeek = udp_pkts_analyzed_by_zeek/udp_orig_pkts
        except ZeroDivisionError:
            udp_packet_rate_analyzed_by_zeek = 0


        final_stats_value = ICMP * icmp_packet_rate_analyzed_by_zeek + TCP * tcp_packet_rate_analyzed_by_zeek + UDP * \
                            udp_packet_rate_analyzed_by_zeek

        return final_stats_value

    def reward_and_punishment_based_on_SLA_events(self, last_trust_score, event):
        """This methods analyses the SLA Breach Predictions and Detections to adapt an ongoing trust score"""
        global newSLAViolation
        "Sliding window definition IN SECONDS"
        CURRENT_TIME_WINDOW = 300
        eigen_factor = 0.02
        n = 10
        number_updates = 0

        offerDID = last_trust_score["trustor"]["offerDID"]
        RP_SLA = last_trust_score["trustor"]["reward_and_punishment_SLA"]
        SLO_list = []
        violation_list = []

        "Loading the SLA Breach Prediction Topic"
        load_dotenv()
        prediction_topic = os.getenv('BREACH_PREDICTION_TOPIC')

        "Defining the offset of the last message"
        last_offset_predictions = 0
        last_offset_violations = 0

        while not event.isSet():
            time.sleep(CURRENT_TIME_WINDOW)
            number_updates+=1

            "Getting the offset of the current message"
            consumer.start(prediction_topic)
            current_offset_predictions = consumer.lastOffset
            consumer.subscribe(prediction_topic)
            breach_notification_list = []
            violation_notification_list = []
            current_breach_prediction_rate = []
            current_sla_violation_rate = []
            last_SLAVRate = 0
            newSLAViolation = False

            if current_offset_predictions > last_offset_predictions:
                "Reading new breach predictions"
                breach_notification_list = consumer.start_reading_breach_events(last_offset_predictions, offerDID)
                for breach_notification in breach_notification_list:
                    type_metric = breach_notification["breachPredictionNotification"]["metric"]
                    "Adding new metrics not previously considered"
                    if type_metric not in SLO_list:
                        SLO_list.append(type_metric)

                    "Update the breach predictions of a metric depending on if it previously had measured in the system"
                    if type_metric+'_breaches' in RP_SLA:
                        RP_SLA[type_metric+'_breaches']['value'] += 1
                    else:
                        RP_SLA[type_metric+'_breaches'] = {"value": 1, "certainty": 1.0}

                "Update the total number of breach predictions"
                RP_SLA["total_breach_predictions"] += len(breach_notification_list)
                current_breach_prediction_rate = self.breach_prediction_rate(SLO_list, RP_SLA)
                last_offset_predictions = current_offset_predictions

            "Since the impact of trust is not linked to the number of new events, it should be calculated one time"
            current_impact_trust = self.impact_trust(last_trust_score["trust_value"])

            "Retrieving new SLA Violations"
            violation_topic = os.getenv('SLA_VIOLATION_TOPIC')
            consumer.start(violation_topic)
            current_offset_violations = consumer.lastOffset
            consumer.subscribe(violation_topic)

            "Obtaining last SLA Violation Rate"
            if 'SLAVRate' in RP_SLA:
                last_SLAVRate = RP_SLA['SLAVRate']

            "Reading new violations"
            violation_notification_list = consumer.start_reading_violation_events(last_offset_violations, offerDID)
            for violation_notification in violation_notification_list:
                type_metric = violation_notification["rule"]["metric"]
                "Adding new metrics not previously considered"
                if type_metric not in violation_list:
                    violation_list.append(type_metric)

            current_sla_violation_rate = self.sla_violation_rate(last_offset_violations, RP_SLA, violation_notification_list, violation_list, number_updates)
            "Updating SLA Violation Rates"
            for violation in violation_list:
                RP_SLA[violation+'_violations'] = current_sla_violation_rate[violation+'_violations']

            "Updating last offset for SLA violations"
            last_offset_violations = current_offset_violations
            "--Generating a set from the two list of metrics"
            metric_set = list(set().union(SLO_list, violation_list))
            BPRate_summation = 0
            SLAVRate_summation = 0
            final_result = 0

            if newSLAViolation and len(SLO_list) > 0:
                "If we have new Violations and Predictions the whole equation is considered"
                for metric in metric_set:
                    if metric+'_breaches' in current_breach_prediction_rate and metric+'_violations' in current_sla_violation_rate:
                        BPRate_summation += current_breach_prediction_rate[metric+'_breaches']
                        SLAVRate_summation += current_sla_violation_rate[metric+'_violations']
                    elif metric+'_breaches' in current_breach_prediction_rate and metric+'_violations' not in current_sla_violation_rate:
                        BPRate_summation += current_breach_prediction_rate[metric+'_breaches']
                    elif metric+'_breaches' not in current_breach_prediction_rate and metric+'_violations' in current_sla_violation_rate:
                        SLAVRate_summation += current_sla_violation_rate[metric+'_violations']

                "Update SLAVRate total"
                try:
                    RP_SLA['SLAVRate'] = SLAVRate_summation / len(violation_list)
                except ZeroDivisionError:
                    RP_SLA['SLAVRate'] = 0

                "Compute the penalization"
                punishment = max(0,((BPRate_summation/len(SLO_list)) + (current_impact_trust * SLAVRate_summation)/len(violation_list))/2)
                final_result = float(last_trust_score ["trust_value"]) - punishment * ((1-float(last_trust_score ["trust_value"]))/5)
            elif newSLAViolation and len(SLO_list) == 0:
                "If we only have new Violations and Predictions the whole equation is considered"
                for metric in metric_set:
                    if metric+'_violations' in current_sla_violation_rate:
                        SLAVRate_summation += current_sla_violation_rate[metric+'_violations']

                "Update SLAVRate total"
                try:
                    RP_SLA['SLAVRate'] = SLAVRate_summation / len(violation_list)
                except ZeroDivisionError:
                    RP_SLA['SLAVRate'] = 0

                "Compute the penalization"
                punishment = max(0,(current_impact_trust * SLAVRate_summation) / len(violation_list))
                final_result = float(last_trust_score ["trust_value"]) - punishment * ((1-float(last_trust_score ["trust_value"]))/5)
            elif not newSLAViolation:
                for metric in metric_set:
                    if metric+'_violations' in RP_SLA:
                        SLAVRate_summation += RP_SLA[metric+'_violations']
                try:
                    reward = min(last_trust_score ["trust_value"] + eigen_factor * ((1-last_trust_score ["trust_value"])/n),1)
                except ZeroDivisionError:
                    reward = last_SLAVRate

                final_result = float(last_trust_score ["trust_value"]) + min(reward,1) * ((1-float(last_trust_score ["trust_value"]))/5)

                "Update SLAVRate total"
                try:
                    RP_SLA['SLAVRate'] = SLAVRate_summation / len(violation_list)
                except ZeroDivisionError:
                    RP_SLA['SLAVRate'] = 0

            print("\n\tPrevious Trust Score", last_trust_score ["trust_value"], " --- Updated Trust Score After SLA-driven Reward and Punishment --->", round(final_result, 4), "\n")
            last_trust_score["trustor"]["reward_and_punishment_SLA"] = RP_SLA
            last_trust_score["trust_value"] = round(final_result, 4)
            last_trust_score["endEvaluationPeriod"] = datetime.timestamp(datetime.now())

            peerTrust.historical.append(last_trust_score)
            #mongoDB.insert_one(last_trust_score)
            itm = mongoDB.find_one({'trustee.offerDID': offerDID, 'trustor.trusteeDID': last_trust_score["trustor"]["trusteeDID"]})
            if itm != None:
                mongoDB.replace_one({'_id': itm.get('_id')}, last_trust_score, True)


    def breach_prediction_rate(self, SLO_list, RP_SLA):
        BP_rate_per_metric = {}
        for SLO in SLO_list:
            "Computing BPRate(u,m)"
            BP_rate = (RP_SLA[SLO+'_breaches']['value'] / RP_SLA['total_breach_predictions']) * RP_SLA[SLO+'_breaches']['certainty']
            BP_rate_per_metric[SLO+'_breaches'] = BP_rate

        return BP_rate_per_metric

    def impact_trust(self, current_trust_score):
        trust_level_impact = trust_fuzzy_set(current_trust_score)
        return (1- (1-current_trust_score)/(1+current_trust_score)) * trust_level_impact

    def sla_violation_rate(self, last_offset_violations, RP_SLA, violation_notification_list, violation_list, number_updates):
        "Sliding window weighting with respect to the forgetting factor"
        global newSLAViolation

        TOTAL_RW = 0.60
        NOW_RW = 1 - TOTAL_RW

        SLAV_rate_per_metric = {}

        if last_offset_violations == 0:
            for violation_notification in violation_notification_list:
                type_metric = violation_notification["rule"]["metric"]
                if type_metric+'_violations' not in RP_SLA:
                    RP_SLA[type_metric+'_violations'] = 1
                else:
                    RP_SLA[type_metric+'_violations'] +=1

            for violation in violation_list:
                SLAV_rate_per_metric[violation+'_violations'] = RP_SLA[violation+'_violations']

            if len(violation_list) > 0:
                newSLAViolation = True

            return SLAV_rate_per_metric

        for violation in violation_list:
            "Computing SLAVRate^t(u,m)"
            "Update the violation of a metric depending on if it previously had measured in the system"
            if violation+'_violations' in RP_SLA:
                previous_SLAVRate = RP_SLA[violation+'_violations']
            else:
                previous_SLAVRate = 0

            new_SLAViolations = 0
            for violation_notification in violation_notification_list:
                if violation_notification["rule"]["metric"] == violation:
                    new_SLAViolations = new_SLAViolations + 1
                    newSLAViolation = True

            if previous_SLAVRate == 0:
                SLAV_rate_per_metric[violation+'_violations'] = new_SLAViolations
            else:
                new_SLAVRate = previous_SLAVRate + TOTAL_RW * (self.increment(new_SLAViolations, previous_SLAVRate)*violation_fuzzy_set(new_SLAViolations, previous_SLAVRate))
                if new_SLAVRate == 0:
                    new_SLAVRate = (previous_SLAVRate*number_updates + new_SLAViolations) / (number_updates+1)

                SLAV_rate_per_metric[violation+'_violations'] = new_SLAVRate

        return SLAV_rate_per_metric

    def increment(self, new_SLAViolations, previous_SLAVRate):
        if new_SLAViolations > previous_SLAVRate:
            return new_SLAViolations/previous_SLAVRate
        return 0

class stop_relationship(Resource):
    def post(self):
        """This method stops a trust relationship"""
        req = request.data.decode("utf-8")
        information = json.loads(req)
        print("\n$$$$$$$$$$$$$$ Finishing a trust relationship with", information['offerDID'],"$$$$$$$$$$$$$$\n")
        for thread in threads_security:
            if information['offerDID'] in thread:
                thread['stop_event'].set()

        for i in range(len(threads_security)):
            if information['offerDID'] in threads_security[i]:
                del threads_security[i]

        for thread in threads_sla:
            if information['offerDID'] in thread:
                thread['stop_event'].set()

        for i in range(len(threads_sla)):
            if information['offerDID'] in threads_sla[i]:
                del threads_sla[i]
                print("\n$$$$$$$$$$$$$$ Finished a trust relationship with", information['offerDID'],"$$$$$$$$$$$$$$\n")
                print("\n$$$$$$$$$$$$$$ Ending update trust level process on", information['offerDID'], "$$$$$$$$$$$$$$\n")
                return 200

        return 400

class query_trust_information(Resource):
    def post(self):
        """ This method will request a recommendation to a given recommender after looking in the interactions in the Data Lake"""
        req = request.data.decode("utf-8")
        information = json.loads(req)

        last_trust_value = consumer.readLastTrustValues(peerTrust.historical, information["trustorDID"],
                                                        information["trusteeDID"], information['last_trustee_interaction_registered'],
                                                        information['currentInteractionNumber'])

        return last_trust_value

class query_trust_score(Resource):
    def post(self):
        """ This method will request a recommendation to a given recommender after looking in the interactions in the Data Lake"""
        req = request.data.decode("utf-8")
        information = json.loads(req)

        last_trust_value = consumer.readLastTrustValueOffer(peerTrust.historical, information["trustorDID"], information["trusteeDID"], information["offerDID"])

        return {'trust_value': last_trust_value["trust_value"]}


class query_satisfaction_score(Resource):
    def post(self):
        """ This method will request a recommendation to a given recommender after looking in the interactions in the Data Lake"""
        req = request.data.decode("utf-8")
        information = json.loads(req)

        last_user_satisfaction = consumer.readSatisfaction(peerTrust.historical, information["trustorDID"], information["trusteeDID"], information["offerDID"])

        return {'userSatisfaction': last_user_satisfaction}

class notify_selection(Resource):
    def post(self):
        """ This method will request a recommendation to a given recommender after looking in the interactions in the Data Lake"""
        req = request.data.decode("utf-8")
        information = json.loads(req)

        "The ISSM sends to the TRMF the final selected offer"
        response = requests.post("http://localhost:5002/update_trust_level", data=json.dumps(information).encode("utf-8"))

        return response.text


def launch_server_REST(port):
    api.add_resource(initialise_offer_type, '/initialise_offer_type')
    api.add_resource(start_data_collection, '/start_data_collection')
    api.add_resource(gather_information, '/gather_information')
    api.add_resource(compute_trust_level, '/compute_trust_level')
    api.add_resource(store_trust_level, '/store_trust_level')
    api.add_resource(update_trust_level, '/update_trust_level')
    api.add_resource(stop_relationship, '/stop_relationship')
    api.add_resource(query_trust_information, '/query_trust_information')
    api.add_resource(query_trust_score, '/query_trust_score')
    api.add_resource(query_satisfaction_score, '/query_satisfaction_score')
    api.add_resource(notify_selection, '/notify_selection')
    http_server = WSGIServer(('0.0.0.0', port), app)
    http_server.serve_forever()

if __name__ == "__main__":
    if len(sys.argv)!=2:
        print("Usage: python3 trustManagementFramework.py [port]")
    else:
        port = int(sys.argv[1])
        launch_server_REST(port)
