#! /usr/bin/env python

import tensorflow as tf
import numpy as np
import os
import shutil
import sys 
import time
import datetime
import corpus_handel
import pickle
from text_cnn import TextCNN
from tensorflow.contrib import learn
import json


learning_rate = 1e-3
trainingDir = "A"
steps = 100
epochs = 10
ckpts = 10

# Parameters
# ==================================================
def train(online,sentence,label):
    # Data loading params
    tf.flags.DEFINE_float("dev_sample_percentage", .1, "Percentage of the training data to use for validation")
    tf.flags.DEFINE_string("positive_data_file", "./data/rt-polaritydata/rt-polarity.pos", "Data source for the positive data.")
    tf.flags.DEFINE_string("negative_data_file", "./data/rt-polaritydata/rt-polarity.neg", "Data source for the negative data.")

    # Model Hyperparameters
    tf.flags.DEFINE_integer("embedding_dim", 128, "Dimensionality of character embedding (default: 128)")
    tf.flags.DEFINE_string("filter_sizes", "3,4,5", "Comma-separated filter sizes (default: '3,4,5')")
    tf.flags.DEFINE_integer("num_filters", 128, "Number of filters per filter size (default: 128)")
    tf.flags.DEFINE_float("dropout_keep_prob", 0.5, "Dropout keep probability (default: 0.5)")
    tf.flags.DEFINE_float("l2_reg_lambda", 0.0, "L2 regularization lambda (default: 0.0)")

    # Training parameters
    tf.flags.DEFINE_integer("batch_size", 64, "Batch Size (default: 64)")
    tf.flags.DEFINE_integer("num_epochs", epochs, "Number of training epochs (default: 200)")
    tf.flags.DEFINE_integer("evaluate_every", 100, "Evaluate model on dev set after this many steps (default: 100)")
    tf.flags.DEFINE_integer("checkpoint_every", ckpts, "Save model after this many steps (default: 100)")
    tf.flags.DEFINE_integer("num_checkpoints", 5, "Number of checkpoints to store (default: 5)")
    # Misc Parameters
    tf.flags.DEFINE_boolean("allow_soft_placement", True, "Allow device soft device placement")
    tf.flags.DEFINE_boolean("log_device_placement", False, "Log placement of ops on devices")
    

    FLAGS = tf.flags.FLAGS
    #FLAGS._parse_flags()
    #print("\nParameters:")
    #for attr, value in sorted(FLAGS.__flags.items()):
    #    print("{}={}".format(attr.upper(), value))
    #print("")

    load_model = False

    # Data Preparation
    # ==================================================

    # Load data
    #print("Loading data...")
    x, y, vocabulary, vocabulary_inv = corpus_handel.load_data(trainingDir)
    if online:
        x, y, vocabulary, vocabulary_inv = corpus_handel.load_data_online(trainingDir,sentence,int(label))
    with open("export/"+trainingDir+"/dictionary.json", "w", encoding="utf8") as outfile:
        json.dump(vocabulary, outfile)
    x_shuffled = np.array([x[0]])
    y_shuffled = np.array([y[0]])
    if not online: 
        # Randomly shuffle data
        np.random.seed(10)
        shuffle_indices = np.random.permutation(np.arange(len(y)))
        x_shuffled = x[shuffle_indices]
        y_shuffled = y[shuffle_indices]

    x_train, x_dev = x_shuffled[:-10], x_shuffled[-10:]
    y_train, y_dev = y_shuffled[:-10], y_shuffled[-10:]
    if online:
        x_train, x_dev = x_shuffled, x_shuffled
        y_train, y_dev = y_shuffled, y_shuffled

    del x, y, x_shuffled, y_shuffled
    sentences, dump = corpus_handel.load_data_and_labels(trainingDir)
    sequence_length = max(len(x) for x in sentences)
    shape = 70 # 
    #print("Vocabulary Size: {:d}".format(len(vocab_processor.vocabulary_)))
    #print("Train/Dev split: {:d}/{:d}".format(len(y_train), len(y_dev)))


    # Training
    # ==================================================

    with tf.Graph().as_default():
        session_conf = tf.ConfigProto(
          allow_soft_placement=FLAGS.allow_soft_placement,
          log_device_placement=FLAGS.log_device_placement)
        sess = tf.Session(config=session_conf)
        with sess.as_default():
            cnn = TextCNN(
                sequence_length=x_train.shape[1],
                num_classes=y_train.shape[1],
                vocab_size=len(vocabulary),
                embedding_size=FLAGS.embedding_dim,
                filter_sizes=list(map(int, FLAGS.filter_sizes.split(","))),
                num_filters=FLAGS.num_filters,
                l2_reg_lambda=FLAGS.l2_reg_lambda)

            # Define Training procedure
            global_step = tf.Variable(0, name="global_step", trainable=False)
            optimizer = tf.train.AdamOptimizer(learning_rate)
            grads_and_vars = optimizer.compute_gradients(cnn.loss)
            train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step)

            # Keep track of gradient values and sparsity (optional)
            grad_summaries = []
            for g, v in grads_and_vars:
                if g is not None:
                    grad_hist_summary = tf.summary.histogram("{}/grad/hist".format(v.name), g)
                    sparsity_summary = tf.summary.scalar("{}/grad/sparsity".format(v.name), tf.nn.zero_fraction(g))
                    grad_summaries.append(grad_hist_summary)
                    grad_summaries.append(sparsity_summary)
            grad_summaries_merged = tf.summary.merge(grad_summaries)

            # Output directory for models and summaries
            #timestamp = str(int(time.time()))
            out_dir = os.path.abspath(os.path.join(os.path.curdir, "runs", trainingDir))
            #print("Writing to {}\n".format(out_dir))

            # Summaries for loss and accuracy
            loss_summary = tf.summary.scalar("loss", cnn.loss)
            acc_summary = tf.summary.scalar("accuracy", cnn.accuracy)

            # Train Summaries
            train_summary_op = tf.summary.merge([loss_summary, acc_summary, grad_summaries_merged])
            train_summary_dir = os.path.join(out_dir, "summaries", "train")
            train_summary_writer = tf.summary.FileWriter(train_summary_dir, sess.graph)

            # Dev summaries
            dev_summary_op = tf.summary.merge([loss_summary, acc_summary])
            dev_summary_dir = os.path.join(out_dir, "summaries", "dev")
            dev_summary_writer = tf.summary.FileWriter(dev_summary_dir, sess.graph)

            if os.path.exists("runs/"+trainingDir+"/checkpoints"):
                load_model = True
            
            # Checkpoint directory. Tensorflow assumes this directory already exists so we need to create it
            checkpoint_dir = os.path.abspath(os.path.join(out_dir, "checkpoints"))
            checkpoint_prefix = os.path.join(checkpoint_dir, "model")
            if not os.path.exists(checkpoint_dir):
                os.makedirs(checkpoint_dir)

            # Write vocabulary
            #vocab_processor.save(os.path.join(out_dir, "vocab"))
            
            # Add an op to initialize the variables.
            init_op = tf.global_variables_initializer()
            saver = tf.train.Saver()#
            if load_model:
                saver.restore(sess, tf.train.latest_checkpoint(checkpoint_dir))
            # Initialize all variables
            if not load_model:
                sess.run(init_op)

            def train_step(x_batch, y_batch):
                """
                A single training step
                """
                feed_dict = {
                  cnn.input_x: x_batch,
                  cnn.input_y: y_batch,
                  cnn.dropout_keep_prob: FLAGS.dropout_keep_prob
                }
                if online: 
                    feed_dict = {
                      cnn.input_x: x_batch,
                      cnn.input_y: y_batch,
                      cnn.dropout_keep_prob: FLAGS.dropout_keep_prob,
                      tf.placeholder(tf.float32, name="learning_rate"): 0.1
                    }
                _, step, summaries, loss, accuracy = sess.run(
                    [train_op, global_step, train_summary_op, cnn.loss, cnn.accuracy],
                    feed_dict)
                time_str = datetime.datetime.now().isoformat()
                if step%10==0:
                    print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
                train_summary_writer.add_summary(summaries, step)

            def dev_step(x_batch, y_batch, writer=None):
                """
                Evaluates model on a dev set
                """
                feed_dict = {
                  cnn.input_x: x_batch,
                  cnn.input_y: y_batch,
                  cnn.dropout_keep_prob: 1.0
                }
                step, summaries, loss, accuracy = sess.run(
                    [global_step, dev_summary_op, cnn.loss, cnn.accuracy],
                    feed_dict)
                time_str = datetime.datetime.now().isoformat()
                print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
                if writer:
                    writer.add_summary(summaries, step)

            # Generate batches
            batches = corpus_handel.batch_iter(
                list(zip(x_train, y_train)), FLAGS.batch_size, FLAGS.num_epochs)
            if online: 
                train_step(x_train, y_train)
                current_step = tf.train.global_step(sess, global_step)
                path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                print("Saved model checkpoint to {}\n".format(path))
                export_path_base = "export"
                try:
                    shutil.rmtree(export_path_base)
                except OSError:
                    pass
                export_path = os.path.join(
                  tf.compat.as_bytes(export_path_base),
                  tf.compat.as_bytes(str(FLAGS.model_version)))
                print('Exporting trained model to', export_path)
                builder = tf.saved_model.builder.SavedModelBuilder(export_path)

                # Build the signature_def_map.

                builder.add_meta_graph_and_variables(sess, [tf.saved_model.tag_constants.SERVING])
                builder.save(True)
            else:
                # Training loop. For each batch...
                for idx,batch in enumerate(batches):
                    if idx < steps*epochs:
                        x_batch, y_batch = zip(*batch)
                        train_step(x_batch, y_batch)
                        current_step = tf.train.global_step(sess, global_step)
                        if current_step % FLAGS.evaluate_every == 0:
                            print("\nEvaluation:")
                            dev_step(x_dev, y_dev, writer=dev_summary_writer)
                            print("")
                        if current_step % FLAGS.checkpoint_every == 0:
                            path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                            print("Saved model checkpoint to {}\n".format(path))
                            export_path_base = "export"
                            try:
                                shutil.rmtree(export_path_base)
                            except OSError:
                                pass
                            export_path = os.path.join(
                              tf.compat.as_bytes(export_path_base),
                              tf.compat.as_bytes(trainingDir))
                            print('Exporting trained model to', export_path)
                            builder = tf.saved_model.builder.SavedModelBuilder(export_path)

                            # Build the signature_def_map.

                            builder.add_meta_graph_and_variables(sess, [tf.saved_model.tag_constants.SERVING])
                            builder.save(True)

if __name__ == '__main__':

    if len(sys.argv) == 3:
        train(True,sys.argv[1],sys.argv[2])
    elif len(sys.argv)== 5:
        trainingDir = sys.argv[1]
        learning_rate = float(sys.argv[2])
        steps = int(sys.argv[3])
        epochs = int(sys.argv[4])
        train(False,"","")
    else:
        train(False,"","")
                