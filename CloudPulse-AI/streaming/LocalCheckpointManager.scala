package cloudpulse.streaming

import java.io.{FileNotFoundException, RandomAccessFile}
import java.nio.file.{Files, LinkOption, Path => NioPath, Paths, StandardCopyOption}
import org.apache.hadoop.conf.Configuration
import org.apache.hadoop.fs.{FSDataInputStream, FSInputStream, FileAlreadyExistsException, FileStatus, Path, PathFilter}
import org.apache.spark.sql.execution.streaming.checkpointing.CheckpointFileManager
import org.apache.spark.sql.execution.streaming.checkpointing.CheckpointFileManager.CancellableFSDataOutputStream
import scala.jdk.CollectionConverters._

/** Local NTFS checkpoints use NIO instead of Hadoop's Windows native filesystem tools. */
final class LocalCheckpointManager(checkpoint: Path, conf: Configuration)
    extends CheckpointFileManager {
  private val root = Paths.get(checkpoint.toUri).toAbsolutePath.normalize()
  private val noFollow = LinkOption.NOFOLLOW_LINKS

  private def local(path: Path): NioPath = {
    val value = Paths.get(path.toUri).toAbsolutePath.normalize()
    require(value.startsWith(root), s"Checkpoint path outside $root: $value")
    value
  }

  override def createAtomic(path: Path, overwrite: Boolean): CancellableFSDataOutputStream = {
    val target = local(path)
    val temporary = Files.createTempFile(target.getParent, ".spark-", ".tmp")
    val output = Files.newOutputStream(temporary)
    new CancellableFSDataOutputStream(output) {
      private var finished = false
      override def close(): Unit = synchronized {
        if (!finished) {
          finished = true
          try {
            output.close()
            if (!overwrite && Files.exists(target, noFollow)) {
              throw new FileAlreadyExistsException(target.toString)
            }
            if (overwrite) {
              Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING)
            } else {
              Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE)
            }
          } finally {
            Files.deleteIfExists(temporary)
          }
        }
      }
      override def cancel(): Unit = synchronized {
        if (!finished) {
          finished = true
          try output.close() finally Files.deleteIfExists(temporary)
        }
      }
    }
  }

  override def open(path: Path): FSDataInputStream = {
    val file = new RandomAccessFile(local(path).toFile, "r")
    new FSDataInputStream(new FSInputStream {
      override def seek(position: Long): Unit = file.seek(position)
      override def getPos: Long = file.getFilePointer
      override def seekToNewSource(position: Long): Boolean = false
      override def read(): Int = file.read()
      override def read(buffer: Array[Byte], offset: Int, length: Int): Int =
        file.read(buffer, offset, length)
      override def close(): Unit = file.close()
    })
  }

  override def list(path: Path, filter: PathFilter): Array[FileStatus] = {
    val directory = local(path)
    if (!Files.exists(directory, noFollow)) throw new FileNotFoundException(path.toString)
    val entries = Files.list(directory)
    try {
      entries.iterator().asScala.map { entry =>
        val hadoopPath = new Path(entry.toUri)
        val directoryEntry = Files.isDirectory(entry, noFollow)
        new FileStatus(
          if (directoryEntry) 0L else Files.size(entry), directoryEntry, 1, 0L,
          Files.getLastModifiedTime(entry, noFollow).toMillis, hadoopPath)
      }.filter(status => filter.accept(status.getPath)).toArray
    } finally entries.close()
  }

  override def mkdirs(path: Path): Unit = { Files.createDirectories(local(path)); () }
  override def exists(path: Path): Boolean = Files.exists(local(path), noFollow)
  override def delete(path: Path): Unit = {
    val target = local(path)
    if (Files.exists(target, noFollow)) {
      val entries = Files.walk(target)
      try entries.sorted(java.util.Comparator.reverseOrder[NioPath]())
        .forEach(entry => Files.deleteIfExists(entry))
      finally entries.close()
    }
  }
  override def isLocal: Boolean = true
  override def createCheckpointDirectory(): Path = new Path(Files.createDirectories(root).toUri)
}
