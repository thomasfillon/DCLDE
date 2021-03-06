"""Copyright (C) 2018  DYNI

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>"""


from tqdm import tqdm, trange
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt

sample_rate = 50000
num_epoch = 160
batch_size = 64

train_set = np.arange(7340)
valid_set = np.arange(3589)


num_feature = int(0.02048 * sample_rate)
k_size1 = 2
k_size2 = 4

n_z = 128


def shuffle():
    click = np.random.permutation(train_set)
    return click


graph = tf.Graph()

with graph.as_default():
    # Input data.
    tf_train_dataset = tf.placeholder(
        tf.float32, shape=(batch_size, 2, num_feature, 1))
    tf_train_noise = tf.placeholder(
        tf.float32, shape=(batch_size, 2, num_feature, 1))

    with tf.name_scope('Variables'):
        conv1_w = tf.Variable(tf.truncated_normal(
            [k_size1, 1, 1, 2*k_size1], stddev=0.1),name='conv1_weight')
        conv2_w = tf.Variable(tf.truncated_normal(
            [1, k_size1, k_size1, 1, 2*k_size1], stddev=0.1),name='conv2_weight')
        conv3_w = tf.Variable(tf.truncated_normal(
            [1, 2*k_size1, 2*k_size1,1 , 1 ], stddev=0.1),name='conv3_weight')
        conv4_w = tf.Variable(tf.truncated_normal(
            [2, k_size1**3, 2*k_size1, 1, 1], stddev=0.1),name='conv4_weight')
        d1_w = tf.Variable(tf.truncated_normal(
            [2*num_feature,n_z], stddev=0.1),name='dense1_weight')


    def variable_summaries(var, name):
        """Attach a lot of summaries to a Tensor (for TensorBoard visualization)."""
        with tf.name_scope(name):
            mean = tf.reduce_mean(var)
            tf.summary.scalar('mean', mean)
            with tf.name_scope('stddev'):
                stddev = tf.sqrt(tf.reduce_mean(tf.square(var - mean)))
            tf.summary.scalar('stddev', stddev)
            tf.summary.scalar('max', tf.reduce_max(var))
            tf.summary.scalar('min', tf.reduce_min(var))
            tf.summary.histogram('histogram', var)

    with tf.name_scope('Summaries'):
        variable_summaries(conv1_w, 'conv1_weight')
        variable_summaries(conv2_w, 'conv2_weight')
        variable_summaries(conv3_w, 'conv3_weight')
        variable_summaries(conv4_w, 'conv4_weight')
        variable_summaries(d1_w, 'dense1_weight')



    with tf.name_scope('model'):
        def enc(data):
            conv1 = tf.nn.conv2d(data, conv1_w, [1,k_size1//2,1,1],'SAME')
            conv2 = tf.nn.conv3d(tf.expand_dims(conv1,4), conv2_w, [1,1,k_size1,1,1],'SAME')
            reshape1 = tf.reshape(conv2,tf.concat([conv2.shape[:-2],[-1,1]],0))
            conv3 = tf.nn.conv3d(reshape1,conv3_w, [1,1,2*k_size1,1,1],'SAME')
            conv4 = tf.nn.conv3d(tf.pad(conv3,[[0,0],[0,0],[k_size1**3//2 -1, k_size1**3//2],[k_size1-1, k_size1],[0,0]]), conv4_w, [1,1,1,1,1],'VALID')
            reshape2 = tf.reshape(conv4,[batch_size,-1])
            z = tf.matmul(reshape2,d1_w)
            return z
			

        def pinv(A, reltol=1e-6):
            # Compute the SVD of the input matrix A
            s, u, v = tf.svd(A)

            # Invert s, clear entries lower than reltol*s[0].
            atol = tf.reduce_max(s) * reltol
            s = tf.boolean_mask(s, s > atol)
            s_inv = tf.diag(1. / s)

            # Compute v * s_inv * u_t * b from the left to avoid forming large intermediate matrices.
            return tf.matmul(v, tf.matmul(s_inv, u, transpose_b=True))

        def dec2(latent):
            undense1 = tf.matmul(latent,pinv(d1_w))
            unshape2 = tf.reshape(undense1,[batch_size, 1, num_feature//8, 4*k_size1**2, 1])
            unconv4 = tf.nn.conv3d_transpose(unshape2,conv4_w, [batch_size,2,num_feature//8+k_size1**3-1, int(conv1_w.shape[-1]*conv2_w.shape[-1])+2*k_size1-1,1],[1,1,1,1,1] , 'VALID')
            unpad4 = unconv4[:,:,k_size1**3//2-1:-k_size1**3//2,k_size1-1:-k_size1]
            unconv3 = tf.nn.conv3d_transpose(unpad4, conv3_w, [batch_size,2,num_feature//2,int(conv1_w.shape[-1]*conv2_w.shape[-1]),1],[1,1,2*k_size1,1,1])
            unshape1 = tf.reshape(unconv3,[batch_size,2,num_feature//2,int(conv1_w.shape[-1]),int(conv2_w.shape[-1])])
            unconv2 = tf.nn.conv3d_transpose(unshape1, conv2_w, [batch_size,2,num_feature,int(conv1_w.shape[-1]),1], [1,1,k_size1,1,1])
            unconv1 = tf.nn.conv2d_transpose(tf.squeeze(unconv2), conv1_w, tf_train_dataset.shape, [1,k_size1//2,1,1])
            return unconv1


        def model(data):
            z = enc(data)
            du = dec2(z)
            return du, z

    # Training computation.
    predict, z, right, tdoa = model(tf_train_dataset) # + tf_train_noise)


    def correlate(a,b,padding='SAME'):
        return tf.transpose(tf.matrix_diag_part(tf.squeeze(tf.transpose(
            tf.nn.conv2d(tf.expand_dims(a, -1),
                         tf.transpose(tf.expand_dims(b, -1), [1, 2, 3, 0]), [1, 1, 1, 1], padding),
            [1, 0, 2, 3]))))

    train_corr = correlate(tf_train_dataset[:,0], tf_train_dataset[:,1])

    middle = (num_feature-1)//2
    tdoa_max = int(sample_rate*0.0012)

    loss_rec_left = tf.losses.mean_squared_error(tf_train_dataset[:, 0], predict[:, 0])
    loss_rec_right = tf.losses.mean_squared_error(tf_train_dataset[:, 1, tdoa_max:-tdoa_max], predict[:, 1, tdoa_max:-tdoa_max])
    loss_rec = ((num_feature) * loss_rec_left + (num_feature - 2*tdoa_max) *loss_rec_right) / (2 * num_feature- 2*tdoa_max)

    loss = loss_rec


    # Optimizer.
    global_step = tf.Variable(0,trainable=False)  # count the number of steps taken.
    learning_rate = tf.train.exponential_decay(0.05, global_step, 20000, 0.1, False)
    optimizer = tf.train.AdamOptimizer(learning_rate).minimize(loss,global_step=global_step)


    # Data saver
    saver = tf.train.Saver(max_to_keep=num_epoch)
    with tf.name_scope('Loss_summaries'):
        tf.summary.scalar('loss',loss)
        tf.summary.scalar('loss_rec',loss_rec)

    merged = tf.summary.merge_all()

    # Gpu config
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True

    with tf.Session(graph=graph,config=config) as session:
        train_writer = tf.summary.FileWriter('log/stereo_ae_dclde/log', session.graph)
        #session = tf_debug.LocalCLIDebugWrapperSession(session)
        tf.global_variables_initializer().run()
        print('Initialized')
        df = np.load('train.npy')
        df_valid = np.load('track9.npy')
        fig, (ax1, ax2, ax3, ax4) = plt.subplots(4,sharex=True)
        plt.show(block=False)
        for epoch in range(num_epoch):
            ml = mlr = mln= mesti = 0
            clicks = shuffle()
            for step in trange(train_size//(batch_size)):

                batch_data = np.expand_dims(
                    df[clicks[step * batch_size:(step + 1) * batch_size]]
                ,3)
                   
                batch_noise = np.random.normal(0,0.025,batch_data.shape)
                batch_data = batch_data / np.sqrt(np.clip(np.square(batch_data).sum((1, 2), keepdims=True), 1e-15, np.infty))
                feed_dict = {tf_train_dataset: batch_data,
                             tf_train_noise: batch_noise}
                _, l, lr, learn, predictions, embed, summary = session.run(
                    [optimizer,loss, loss_rec, learning_rate, predict, z, merged], feed_dict=feed_dict)

                ml += l
                mlr += lr
                mln += learn
                train_writer.add_summary(summary, step + epoch *(train_size//(batch_size)))

                if (step%25 == 24):
                    tqdm.write(f'Minibatch loss at step {step}:\n total : {ml}, reconstruction : {mlr}, learning rate : {mln/25}')
                    ml = mlr = mln = 0
                    r = np.random.randint(batch_size)
                    ax1.clear()
                    ax2.clear()
                    ax3.clear()
                    ax4.clear()
                    ax1.plot(batch_data[r,0,:,0])
                    ax2.plot(predictions[r,0,:,0])
                    ax3.plot(batch_data[r,1,:,0])
                    ax4.plot(predictions[r,1,:,0])
                    plt.draw()
                    plt.show(block=False)
                    plt.pause(0.01)

            ml = 0
            for step in trange(len(valid_set)//(batch_size)):

                batch_data = np.expand_dims(
                    df_valid[valid_set[step * batch_size:(step + 1) * batch_size]]
                    ,3)
					
					
                batch_noise = np.random.normal(0,0.025,batch_data.shape)
                batch_data = batch_data / np.sqrt(np.clip(np.square(batch_data).sum((1, 2), keepdims=True), 1e-15, np.infty))
                feed_dict = {tf_train_dataset: batch_data,
                             tf_train_noise: batch_noise}
                l = session.run(loss, feed_dict=feed_dict)
                ml +=l
            mml = ml / (len(valid_set)//(batch_size))
            print(f'Validation loss for epoch {epoch} : total : {ml}, mean : {mml}, 25*mean : {25*mml}')
            saver.save(session, f'log/stereo_ae_dclde/weight/epoch{epoch}.ckpt')